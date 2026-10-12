"""AGENTIC TASK 4: Reminder agent (deadlines, interviews, tests -> Google Calendar).

extract -> validate -> (retry extract once if nothing valid) -> plan -> [user reviews and approves in the UI] -> create events

The model only READS dates out of text. Code validates every date and time, plans the reminders
(deadline: heads-up days before; interview: a day and an hour before plus a prep block), and the
calendar is only touched after the user clicks approve. Events are inserted only, never edited or deleted.
"""
from __future__ import annotations

import hashlib
import operator
import re
from datetime import date, datetime, timedelta
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from .. import llm, prompts, security, store
from ..schemas import PlannedReminder, ReminderExtraction
from ..tools import calendar_tool

IST = calendar_tool.IST
MAX_DAYS_AHEAD = 400
MAX_PER_BATCH = 10
MAX_PER_SESSION = 30

KIND_LABEL = {
    "deadline": "Application deadline", "interview": "Interview", "test": "Online test",
    "follow_up": "Follow up", "prep": "Preparation", "other": "Reminder",
}


# ------------------------------------------------------------- code fallback
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december", "sept", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_MON = "|".join(_MONTHS)
MONTH_NUM = {m: (i % 12) + 1 for i, m in enumerate(_MONTHS[:12])}
MONTH_NUM.update({"sept": 9, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9,
                  "oct": 10, "nov": 11, "dec": 12})

_DATE_PATTERNS = [
    re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b"),
    re.compile(rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\b\s+(?P<mon>{_MON})\b\.?(?:,?\s+(?P<y>\d{{4}})\b)?", re.I),
    re.compile(rf"\b(?P<mon>{_MON})\b\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(?P<y>\d{{4}})\b)?", re.I),
    re.compile(r"\b(?P<d>\d{1,2})[/-](?P<m>\d{1,2})[/-](?P<y>\d{4})\b"),  # India: day first
]
_KIND_PATTERNS = {
    "interview": re.compile(r"interview|hr round|technical round|panel round", re.I),
    "test": re.compile(r"online test|assessment|coding (?:test|round)|aptitude|hackathon|written test|\bOA\b", re.I),
    "deadline": re.compile(
        r"last date|deadline|apply by|apply before|applications? (?:close|closes|closing)|closes?|closing|due|submit by|register by", re.I),
    "follow_up": re.compile(r"follow[- ]?up", re.I),
}
_TIME_12 = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.I)
_TIME_24 = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")


def _segment(text: str, s: int, e: int) -> tuple[str, int]:
    left = max(text.rfind("\n", 0, s), text.rfind(";", 0, s), text.rfind(". ", 0, s))
    rights = [i for i in (text.find("\n", e), text.find(";", e), text.find(". ", e)) if i != -1]
    right = min(rights) if rights else len(text)
    return text[left + 1:right], s - (left + 1)


def _nearest_kind(seg: str, pos: int) -> str:
    best, best_d = "other", 10**6
    for kind, pat in _KIND_PATTERNS.items():
        for m in pat.finditer(seg):
            d = pos - m.end() if m.end() <= pos else (m.start() - pos) + 25  # keyword before the date wins
            if d < best_d:
                best, best_d = kind, d
    return best


def _nearest_time(seg: str, pos: int) -> str:
    found = []
    for m in _TIME_12.finditer(seg):
        h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0)
        mi = int(m.group(2) or 0)
        if int(m.group(1)) <= 12 and mi < 60:
            found.append((abs(m.start() - pos), f"{h:02d}:{mi:02d}"))
    for m in _TIME_24.finditer(seg):
        found.append((abs(m.start() - pos), f"{int(m.group(1)):02d}:{m.group(2)}"))
    return min(found)[1] if found else ""


def regex_extract(text: str, today: date, company: str = "", role: str = "") -> list[dict]:
    """Deterministic date finder used when no AI model is available (and as a safety net)."""
    out, spans = [], []
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text):
            if any(m.start() < b and a < m.end() for a, b in spans):
                continue
            g = m.groupdict()
            try:
                day = int(g["d"])
                month = int(g["m"]) if g.get("m") else MONTH_NUM[g["mon"].lower()]
                year = int(g["y"]) if g.get("y") else today.year
                d = date(year, month, day)
                if not g.get("y") and d < today:
                    d = date(year + 1, month, day)
            except (ValueError, KeyError):
                continue
            spans.append((m.start(), m.end()))
            seg, pos = _segment(text, m.start(), m.end())
            out.append({"kind": _nearest_kind(seg, pos), "title": role, "company": company,
                        "date": d.isoformat(), "time": _nearest_time(seg, pos)})
    seen, uniq = set(), []
    for c in sorted(out, key=lambda c: c["date"]):
        k = (c["kind"], c["date"], c["time"])
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    return uniq


# --------------------------------------------------------------- validation
def validate_candidates(cands: list[dict], today: date) -> tuple[list[dict], list[str]]:
    """Keep only real, future, sensible dates. Returns (valid, reasons_dropped)."""
    valid, dropped = [], []
    for c in cands:
        kind = c.get("kind") if c.get("kind") in ("deadline", "interview", "test", "follow_up", "other") else "other"
        try:
            d = date.fromisoformat(str(c.get("date", "")))
        except ValueError:
            dropped.append(f"'{str(c.get('date', ''))[:20]}' is not a valid date")
            continue
        if d < today:
            dropped.append(f"{d.isoformat()} is in the past")
            continue
        if d > today + timedelta(days=MAX_DAYS_AHEAD):
            dropped.append(f"{d.isoformat()} is more than {MAX_DAYS_AHEAD} days away")
            continue
        t = str(c.get("time") or "").strip()
        if t:
            try:
                hh, mm = (int(x) for x in t.split(":"))
                datetime(2000, 1, 1, hh, mm)
                t = f"{hh:02d}:{mm:02d}"
            except (ValueError, TypeError):
                t = ""
        valid.append({
            "kind": kind, "title": security.strip_html(str(c.get("title") or ""), 80),
            "company": security.strip_html(str(c.get("company") or ""), 60), "date": d.isoformat(), "time": t,
        })
    return valid, dropped


# ----------------------------------------------------------------- planning
def _key(kind: str, title: str, d: str, t: str) -> str:
    return hashlib.md5(f"{kind}|{title.lower()}|{d}|{t}".encode()).hexdigest()[:16]


def _title(kind: str, title: str, company: str) -> str:
    s = KIND_LABEL[kind]
    if title:
        s += f": {title}"
    if company:
        s += f" at {company}"
    return s[:120]


def _keep_future(mins: list[int], start: datetime, now: datetime) -> list[int]:
    return [m for m in mins if start - timedelta(minutes=m) > now]


def plan_items(valid: list[dict], today: date, now: datetime | None = None) -> list[dict]:
    """Decide the calendar entries and their reminders. Pure code, so it is predictable and testable."""
    now = now or datetime.now(IST)
    plan: list[PlannedReminder] = []
    for c in valid:
        kind, d = c["kind"], date.fromisoformat(c["date"])
        title, company, t = c["title"], c["company"], c["time"]
        note = ""
        if kind == "deadline" and not t:
            all_day, tm, dur = True, "", 60
            start = datetime.combine(d, datetime.min.time(), tzinfo=IST)
            mins = _keep_future([900, 3780], start, now)  # 9:00 the day before, and 3 days before
            note = "Reminders: 9:00 the day before and 3 days before."
        else:
            all_day = False
            if not t:
                t = "10:00"
                note = "No time was given, so 10:00 IST is assumed. Change it in Calendar if needed."
            tm = t
            hh, mm = (int(x) for x in t.split(":"))
            start = datetime.combine(d, datetime.min.time().replace(hour=hh, minute=mm), tzinfo=IST)
            base = {"deadline": [1440, 180], "interview": [1440, 60], "test": [1440, 60],
                    "follow_up": [30], "other": [1440]}[kind]
            mins = _keep_future(base, start, now)
            dur = {"deadline": 30, "interview": 60, "test": 90}.get(kind, 60)
        plan.append(PlannedReminder(
            kind=kind, title=_title(kind, title, company), company=company, date=c["date"], time=tm,
            all_day=all_day, duration_min=dur, reminders_min=mins, note=note, key=_key(kind, title + company, c["date"], tm),
        ))
        if kind in ("interview", "test"):
            prep_day = d - timedelta(days=1)
            prep_start = datetime.combine(prep_day, datetime.min.time().replace(hour=18), tzinfo=IST)
            if prep_day >= today and prep_start > now:
                what = "interview" if kind == "interview" else "online test"
                ptitle = f"Prepare for {what}" + (f": {title}" if title else "") + (f" at {company}" if company else "")
                plan.append(PlannedReminder(
                    kind="prep", title=ptitle[:120], company=company, date=prep_day.isoformat(), time="18:00",
                    duration_min=60, reminders_min=[30], note="Revise your resume, the job description and your weak skills.",
                    key=_key("prep", title + company, prep_day.isoformat(), "18:00"),
                ))
    return [p.model_dump() for p in plan][:MAX_PER_BATCH]


# -------------------------------------------------------------------- graph
class RState(TypedDict, total=False):
    text: str
    today: str
    now: str
    company: str
    role: str
    use_llm: bool
    candidates: list
    valid: list
    retries: int
    retry: bool
    feedback: str
    plan: list
    log: Annotated[list, operator.add]


def extract(state: RState) -> dict:
    today = date.fromisoformat(state["today"])
    text = security.clean_text(state.get("text", ""), 6000)
    company, role = state.get("company", ""), state.get("role", "")
    cands: list[dict] = []
    log = []
    if state.get("use_llm", True) and llm.available():
        user = f"Today's date: {today.isoformat()} ({today.strftime('%A')})\n{security.wrap('doc', text)}"
        if state.get("feedback"):
            user += "\nFix these problems from your last attempt: " + state["feedback"]
        try:
            got = llm.structured(ReminderExtraction, prompts.REMIND_EXTRACT_SYSTEM, user, tier="fast", temperature=0.0)
            cands = [c.model_dump() for c in got.items][:20]
            if cands:
                log.append(f"Read the text with the AI model and found {len(cands)} possible date(s).")
        except (llm.LLMUnavailable, ValueError):
            cands = []
    if not cands:
        cands = regex_extract(text, today, company, role)
        log.append(f"Read the text in code and found {len(cands)} possible date(s).")
    for c in cands:  # fill gaps from what the user typed in the form
        c["company"] = c.get("company") or company
        c["title"] = c.get("title") or role
    return {"candidates": cands, "log": log}


def validate(state: RState) -> dict:
    today = date.fromisoformat(state["today"])
    valid, dropped = validate_candidates(state.get("candidates", []), today)
    log = []
    if dropped:
        log.append("Dropped: " + "; ".join(dropped[:4]) + ".")
    retry = bool(
        not valid and state.get("candidates") and state.get("retries", 0) < 1
        and state.get("use_llm", True) and llm.available()
    )
    fb = ("These dates were rejected: " + "; ".join(dropped[:4]) + ". Use dates that are today or later.") if retry else ""
    if retry:
        log.append("No usable dates, so the agent is reading the text again.")
    return {"valid": valid, "retry": retry, "retries": state.get("retries", 0) + (1 if retry else 0),
            "feedback": fb, "log": log}


def _after_validate(state: RState) -> str:
    return "extract" if state.get("retry") else "plan"


def plan(state: RState) -> dict:
    today = date.fromisoformat(state["today"])
    items = plan_items(state.get("valid", []), today, datetime.fromisoformat(state["now"]))
    msg = f"Planned {len(items)} calendar entr{'y' if len(items) == 1 else 'ies'}." if items else "No usable dates found."
    return {"plan": items, "log": [msg]}


def build_graph():
    g = StateGraph(RState)
    g.add_node("extract", extract)
    g.add_node("validate", validate)
    g.add_node("plan", plan)
    g.add_edge(START, "extract")
    g.add_edge("extract", "validate")
    g.add_conditional_edges("validate", _after_validate, {"extract": "extract", "plan": "plan"})
    g.add_edge("plan", END)
    return g.compile()


_GRAPH = None


def run_reminder_agent(text: str, company: str = "", role: str = "", use_llm: bool = True,
                       today: date | None = None) -> dict:
    """Read text, find dates, plan reminders. Returns {'plan': [...], 'log': [...]}. Nothing is created yet."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    now = datetime.combine(today, datetime.min.time().replace(hour=9), tzinfo=IST) if today else datetime.now(IST)
    out = _GRAPH.invoke({
        "text": text, "today": now.date().isoformat(), "now": now.isoformat(), "company": company.strip()[:60],
        "role": role.strip()[:80], "use_llm": use_llm, "retries": 0, "log": [],
    })
    return {"plan": out.get("plan", []), "log": out.get("log", [])}


def plan_manual(kind: str, title: str, company: str, date_iso: str, time_hhmm: str = "",
                today: date | None = None) -> list[dict]:
    """Quick-add path with no AI: the same validation and planning as the agent."""
    today = today or datetime.now(IST).date()
    valid, dropped = validate_candidates(
        [{"kind": kind, "title": title, "company": company, "date": date_iso, "time": time_hhmm}], today)
    if not valid:
        raise ValueError(dropped[0] if dropped else "That date cannot be used.")
    return plan_items(valid, today)


# ------------------------------------------------------- after approval only
def create_events(session_id: str, items: list[dict], approved: bool) -> dict:
    """Add the chosen reminders. Needs approved=True. Insert only; duplicates are skipped.

    Returns {'results': [{title, date, status}], 'ics': str}. When Google Calendar is not connected
    (or rejects an event) the event is saved as an .ics download instead.
    """
    if approved is not True:
        raise calendar_tool.CalendarError("Reminders were not approved by the user.")
    existing = len(store.list_reminders(session_id))
    room = max(0, MAX_PER_SESSION - existing)
    chosen = [i for i in items if i.get("add", True)][: min(MAX_PER_BATCH, room)]
    results, ics_items = [], []
    for it in chosen:
        row = {"title": it.get("title", ""), "date": it.get("date", ""), "status": ""}
        try:
            calendar_tool.reminder_event_body(it)  # validates every field
        except calendar_tool.CalendarError as e:
            row["status"] = f"skipped: {e}"
            results.append(row)
            continue
        if store.reminder_exists(session_id, it.get("key", "")):
            row["status"] = "already added"
            results.append(row)
            continue
        try:
            event_id = calendar_tool.create_reminder_event(True, it)
            store.insert_reminder(session_id, it, "created", event_id)
            row["status"] = "created"
        except calendar_tool.CalendarError:
            store.insert_reminder(session_id, it, "ics only")
            ics_items.append(it)
            row["status"] = "ics only"
        results.append(row)
    return {"results": results, "ics": calendar_tool.build_ics_many(ics_items) if ics_items else ""}
