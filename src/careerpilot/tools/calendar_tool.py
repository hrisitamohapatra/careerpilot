"""Google Calendar follow-up events (minimal scope) and an .ics fallback.

Only creates ONE kind of event, only after approval. Never edits or deletes anything.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .. import config, security

TOKEN_FILE = config.ROOT / "token.json"


class CalendarError(RuntimeError):
    pass


class CalendarNotConnected(CalendarError):
    pass


def _credentials_file() -> Path:
    name = config.env("GOOGLE_CREDENTIALS_FILE") or "credentials.json"
    p = Path(name)
    return p if p.is_absolute() else config.ROOT / p


def has_client_secrets() -> bool:
    return _credentials_file().exists()


def _load_creds():
    if not TOKEN_FILE.exists():
        return None
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), [config.CALENDAR_SCOPE])
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _write_token(creds.to_json())
        return creds if creds and creds.valid else None
    except Exception:  # noqa: BLE001
        return None


def _write_token(data: str) -> None:
    TOKEN_FILE.write_text(data, encoding="utf-8")
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass


def is_connected() -> bool:
    return _load_creds() is not None


def connect() -> None:
    """Run the desktop OAuth flow (opens the browser). Requests ONLY calendar.events."""
    if not has_client_secrets():
        raise CalendarError("credentials.json not found. See the README for how to create it.")
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(_credentials_file()), [config.CALENDAR_SCOPE])
    creds = flow.run_local_server(port=0)
    _write_token(creds.to_json())


def _clean(s: str, n: int) -> str:
    return " ".join((s or "").replace("\r", " ").replace("\n", " ").split())[:n]


def event_fields(role: str, company: str, url: str, score: float | None, follow_up: date) -> dict:
    """Build the event from validated values only."""
    role, company = _clean(role, 100), _clean(company, 100)
    link = url if (url or "").startswith(("http://", "https://")) else ""
    desc = f"Follow up on your application for {role} at {company}."
    if link:
        desc += f"\nApply link: {_clean(link, 500)}"
    if score is not None:
        desc += f"\nMatch score: {score:.0f}/100"
    start = datetime.combine(follow_up, datetime.min.time()).replace(hour=10)
    end = start + timedelta(hours=1)
    return {
        "summary": f"Follow up: {role} at {company}",
        "description": desc,
        "start": {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": end.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "Asia/Kolkata"},
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 30}]},
    }


def create_followup_event(approved: bool, role: str, company: str, url: str,
                          score: float | None, follow_up: date) -> str:
    """Create the follow-up event. Returns the Google event id."""
    if approved is not True:
        raise CalendarError("Calendar event was not approved by the user.")
    if not isinstance(follow_up, date):
        raise CalendarError("Follow-up date is not valid.")
    creds = _load_creds()
    if creds is None:
        raise CalendarNotConnected("Google Calendar is not connected.")
    try:
        from googleapiclient.discovery import build

        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        ev = service.events().insert(calendarId="primary", body=event_fields(role, company, url, score, follow_up)).execute()
        return str(ev.get("id", ""))
    except Exception:  # noqa: BLE001
        raise CalendarError("Google Calendar rejected the event. Try reconnecting.")


def _ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def build_ics(role: str, company: str, url: str, score: float | None, follow_up: date) -> str:
    """A standards-compliant .ics file (10:00 IST = 04:30 UTC) with a 30-minute popup alarm."""
    f = event_fields(role, company, url, score, follow_up)
    start = datetime.combine(follow_up, datetime.min.time()).replace(hour=4, minute=30, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    fmt = "%Y%m%dT%H%M%SZ"
    uid = f"{start.strftime(fmt)}-{abs(hash((role, company))) % 10**8}@careerpilot"
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CareerPilot//EN", "BEGIN:VEVENT",
        f"UID:{uid}", f"DTSTAMP:{datetime.now(timezone.utc).strftime(fmt)}",
        f"DTSTART:{start.strftime(fmt)}", f"DTEND:{end.strftime(fmt)}",
        f"SUMMARY:{_ics_escape(f['summary'])}", f"DESCRIPTION:{_ics_escape(f['description'])}",
        "BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:Follow up", "TRIGGER:-PT30M", "END:VALARM",
        "END:VEVENT", "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


# ======================================================================
# Reminder agent events (deadlines, interviews, tests, prep blocks)
# ======================================================================
KINDS = ("deadline", "interview", "test", "follow_up", "prep", "other")
MAX_REMINDER_MINUTES = 40320  # Google Calendar allows up to 4 weeks
IST = timezone(timedelta(hours=5, minutes=30))


def _validated(item: dict) -> dict:
    """Re-check every field of a planned reminder in code. Nothing from the model is trusted here."""
    kind = item.get("kind")
    if kind not in KINDS:
        raise CalendarError("Unknown reminder type.")
    try:
        d = date.fromisoformat(str(item.get("date", "")))
    except ValueError:
        raise CalendarError("Reminder date is not valid.")
    all_day = bool(item.get("all_day"))
    hh = mm = 0
    if not all_day:
        try:
            hh, mm = (int(x) for x in str(item.get("time", "")).split(":"))
            datetime(2000, 1, 1, hh, mm)
        except (ValueError, TypeError):
            raise CalendarError("Reminder time is not valid.")
    try:
        mins = [int(m) for m in (item.get("reminders_min") or [])][:5]
        dur = min(480, max(15, int(item.get("duration_min") or 60)))
    except (ValueError, TypeError):
        raise CalendarError("Reminder settings are not valid.")
    if any(m < 0 or m > MAX_REMINDER_MINUTES for m in mins):
        raise CalendarError("Reminder offset is not valid.")
    title = _clean(item.get("title", ""), 120)
    if not title:
        raise CalendarError("Reminder title is empty.")
    note = _clean(item.get("note", ""), 200)
    desc = "Added by CareerPilot." + (f" {note}" if note else "")
    return {"kind": kind, "date": d, "all_day": all_day, "hh": hh, "mm": mm, "mins": mins, "dur": dur,
            "title": title, "desc": desc, "key": _clean(item.get("key", ""), 64)}


def reminder_event_body(item: dict) -> dict:
    """Google Calendar event body for one planned reminder (built from validated values only)."""
    v = _validated(item)
    if v["all_day"]:
        start = {"date": v["date"].isoformat()}
        end = {"date": (v["date"] + timedelta(days=1)).isoformat()}
    else:
        s = datetime.combine(v["date"], datetime.min.time()).replace(hour=v["hh"], minute=v["mm"])
        e = s + timedelta(minutes=v["dur"])
        start = {"dateTime": s.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "Asia/Kolkata"}
        end = {"dateTime": e.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "Asia/Kolkata"}
    reminders = (
        {"useDefault": False, "overrides": [{"method": "popup", "minutes": m} for m in v["mins"]]}
        if v["mins"] else {"useDefault": True}
    )
    body = {"summary": v["title"], "description": v["desc"], "start": start, "end": end, "reminders": reminders}
    if v["key"]:
        body["extendedProperties"] = {"private": {"careerpilot_key": v["key"]}}
    return body


def create_reminder_event(approved: bool, item: dict) -> str:
    """Insert ONE reminder event (never edits or deletes). Returns the Google event id."""
    if approved is not True:
        raise CalendarError("Calendar event was not approved by the user.")
    body = reminder_event_body(item)  # validates first
    creds = _load_creds()
    if creds is None:
        raise CalendarNotConnected("Google Calendar is not connected.")
    try:
        from googleapiclient.discovery import build

        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        ev = service.events().insert(calendarId="primary", body=body).execute()
        return str(ev.get("id", ""))
    except Exception:  # noqa: BLE001
        raise CalendarError("Google Calendar rejected the event. Try reconnecting.")


def build_ics_many(items: list[dict]) -> str:
    """One .ics file with every planned reminder (fallback when Calendar is not connected)."""
    import hashlib

    fmt = "%Y%m%dT%H%M%SZ"
    stamp = datetime.now(timezone.utc).strftime(fmt)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CareerPilot//EN"]
    for it in items:
        v = _validated(it)
        uid = hashlib.md5((v["key"] or v["title"] + v["date"].isoformat()).encode()).hexdigest() + "@careerpilot"
        lines += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}"]
        if v["all_day"]:
            lines += [f"DTSTART;VALUE=DATE:{v['date'].strftime('%Y%m%d')}",
                      f"DTEND;VALUE=DATE:{(v['date'] + timedelta(days=1)).strftime('%Y%m%d')}"]
        else:
            s = datetime.combine(v["date"], datetime.min.time()).replace(hour=v["hh"], minute=v["mm"], tzinfo=IST)
            e = s + timedelta(minutes=v["dur"])
            lines += [f"DTSTART:{s.astimezone(timezone.utc).strftime(fmt)}", f"DTEND:{e.astimezone(timezone.utc).strftime(fmt)}"]
        lines += [f"SUMMARY:{_ics_escape(v['title'])}", f"DESCRIPTION:{_ics_escape(v['desc'])}"]
        for m in v["mins"]:
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_ics_escape(v['title'])}", f"TRIGGER:-PT{m}M", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
