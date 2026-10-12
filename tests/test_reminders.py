from datetime import date, datetime

import pytest

from careerpilot import graph, llm, store
from careerpilot.nodes import reminders as rem
from careerpilot.nodes import router
from careerpilot.schemas import ReminderCandidate, ReminderExtraction
from careerpilot.tools import calendar_tool

TODAY = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=calendar_tool.IST)
TEXT = "Last date to apply: 30 Oct 2026. Interview on 5 Nov 2026 at 11:30 am."


# ------------------------------------------------------------ code fallback
def test_regex_finds_deadline_and_interview_with_time():
    c = rem.regex_extract(TEXT, TODAY)
    assert [(x["kind"], x["date"], x["time"]) for x in c] == [
        ("deadline", "2026-10-30", ""), ("interview", "2026-11-05", "11:30")]


@pytest.mark.parametrize("text,expected", [
    ("Interview on 05/11/2026", "2026-11-05"),          # India: day first
    ("Interview on Nov 5, 2026", "2026-11-05"),
    ("Interview on 2026-11-05", "2026-11-05"),
    ("Interview on 5th November", "2026-11-05"),        # no year: next occurrence
    ("Interview on 5 Jan", "2027-01-05"),               # already passed this year -> next year
])
def test_regex_date_formats(text, expected):
    assert rem.regex_extract(text, TODAY)[0]["date"] == expected


def test_two_dates_in_one_sentence_get_their_own_kind():
    c = rem.regex_extract("Apply by 25 Oct and interview on 3 Nov at 2 pm", TODAY)
    assert [(x["kind"], x["date"]) for x in c] == [("deadline", "2026-10-25"), ("interview", "2026-11-03")]
    assert c[1]["time"] == "14:00"


def test_market_5_is_not_a_date():
    assert rem.regex_extract("The market 5 times bigger", TODAY) == []


# ----------------------------------------------------------- validation
def test_validate_drops_past_and_far_future_and_garbage():
    valid, dropped = rem.validate_candidates([
        {"kind": "deadline", "date": "2026-10-01"}, {"kind": "deadline", "date": "2030-01-01"},
        {"kind": "deadline", "date": "not a date"}, {"kind": "hack", "date": "2026-10-20", "time": "99:99"},
    ], TODAY)
    assert len(valid) == 1 and valid[0]["kind"] == "other" and valid[0]["time"] == ""
    assert len(dropped) == 3


# ------------------------------------------------------------- planning
def test_deadline_is_all_day_with_two_reminders():
    p = rem.plan_items([{"kind": "deadline", "title": "SDE-1", "company": "Acme", "date": "2026-10-30", "time": ""}], TODAY, NOW)
    assert len(p) == 1 and p[0]["all_day"] and p[0]["reminders_min"] == [900, 3780]
    assert p[0]["title"] == "Application deadline: SDE-1 at Acme"


def test_interview_gets_reminders_and_prep_block():
    p = rem.plan_items([{"kind": "interview", "title": "SDE-1", "company": "Acme", "date": "2026-11-05", "time": "11:30"}], TODAY, NOW)
    main, prep = p
    assert main["reminders_min"] == [1440, 60] and not main["all_day"] and main["time"] == "11:30"
    assert prep["kind"] == "prep" and prep["date"] == "2026-11-04" and prep["time"] == "18:00"
    assert prep["title"] == "Prepare for interview: SDE-1 at Acme"


def test_missing_interview_time_is_assumed_and_flagged():
    p = rem.plan_items([{"kind": "interview", "title": "", "company": "", "date": "2026-11-05", "time": ""}], TODAY, NOW)
    assert p[0]["time"] == "10:00" and "assumed" in p[0]["note"]


def test_reminders_that_would_already_have_fired_are_dropped():
    soon = datetime(2026, 10, 12, 20, 0, tzinfo=calendar_tool.IST)
    p = rem.plan_items([{"kind": "interview", "title": "", "company": "", "date": "2026-10-13", "time": "09:00"}], TODAY, soon)
    assert p[0]["reminders_min"] == [60]            # 24h before is already past
    assert all(x["kind"] != "prep" for x in p)      # prep block (18:00 today) is past


def test_agent_offline_end_to_end():
    out = rem.run_reminder_agent(TEXT, company="Acme", role="SDE-1", use_llm=False, today=TODAY)
    titles = [x["title"] for x in out["plan"]]
    assert titles == ["Application deadline: SDE-1 at Acme", "Interview: SDE-1 at Acme",
                      "Prepare for interview: SDE-1 at Acme"]
    assert any("in code" in line for line in out["log"])


def test_agent_retries_once_when_model_returns_only_past_dates(monkeypatch):
    calls = []

    def fake(schema, system, user, **k):
        calls.append(user)
        date_ = "2025-01-01" if len(calls) == 1 else "2026-11-05"
        return ReminderExtraction(items=[ReminderCandidate(kind="interview", title="SDE-1", date=date_, time="11:00")])

    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "structured", fake)
    out = rem.run_reminder_agent("interview soon", today=TODAY)
    assert len(calls) == 2 and "rejected" in calls[1]
    assert out["plan"] and out["plan"][0]["date"] == "2026-11-05"
    assert any("reading the text again" in line for line in out["log"])


def test_plan_manual_validates():
    assert rem.plan_manual("deadline", "SDE-1", "Acme", "2026-10-30", today=TODAY)
    with pytest.raises(ValueError):
        rem.plan_manual("deadline", "SDE-1", "Acme", "2020-01-01", today=TODAY)


# ----------------------------------------------------- calendar side
def test_calendar_bodies():
    allday = calendar_tool.reminder_event_body(rem.plan_items(
        [{"kind": "deadline", "title": "SDE-1", "company": "Acme", "date": "2026-10-30", "time": ""}], TODAY, NOW)[0])
    assert allday["start"] == {"date": "2026-10-30"} and allday["end"] == {"date": "2026-10-31"}
    assert allday["reminders"]["overrides"] == [{"method": "popup", "minutes": 900}, {"method": "popup", "minutes": 3780}]
    timed = calendar_tool.reminder_event_body(rem.plan_items(
        [{"kind": "interview", "title": "SDE-1", "company": "Acme", "date": "2026-11-05", "time": "11:30"}], TODAY, NOW)[0])
    assert timed["start"] == {"dateTime": "2026-11-05T11:30:00", "timeZone": "Asia/Kolkata"}
    assert timed["end"]["dateTime"] == "2026-11-05T12:30:00"
    assert timed["extendedProperties"]["private"]["careerpilot_key"]


@pytest.mark.parametrize("bad", [
    {"kind": "x", "date": "2026-11-05", "time": "10:00", "title": "t"},
    {"kind": "interview", "date": "2026-13-45", "time": "10:00", "title": "t"},
    {"kind": "interview", "date": "2026-11-05", "time": "25:00", "title": "t"},
    {"kind": "interview", "date": "2026-11-05", "time": "10:00", "title": "t", "reminders_min": [999999]},
    {"kind": "interview", "date": "2026-11-05", "time": "10:00", "title": "  "},
])
def test_calendar_rejects_invalid_items(bad):
    with pytest.raises(calendar_tool.CalendarError):
        calendar_tool.reminder_event_body(bad)


def test_create_reminder_event_needs_approval():
    item = rem.plan_items([{"kind": "deadline", "title": "", "company": "", "date": "2026-10-30", "time": ""}], TODAY, NOW)[0]
    for flag in (False, None, 1):
        with pytest.raises(calendar_tool.CalendarError):
            calendar_tool.create_reminder_event(flag, item)


def test_title_newlines_cannot_break_event_or_ics():
    item = {"kind": "interview", "title": "SDE\r\nBEGIN:VEVENT", "date": "2026-11-05", "time": "10:00", "reminders_min": [60]}
    body = calendar_tool.reminder_event_body(item)
    assert "\n" not in body["summary"] and "\r" not in body["summary"]
    ics = calendar_tool.build_ics_many([item])
    lines = ics.split("\r\n")
    assert lines.count("BEGIN:VEVENT") == 1 and lines.count("END:VEVENT") == 1  # the title stayed on one line


def test_ics_many_formats_and_ist_to_utc():
    plan = rem.plan_items([
        {"kind": "deadline", "title": "A", "company": "", "date": "2026-10-30", "time": ""},
        {"kind": "interview", "title": "A", "company": "", "date": "2026-11-05", "time": "11:30"}], TODAY, NOW)
    ics = calendar_tool.build_ics_many(plan)
    assert "DTSTART;VALUE=DATE:20261030" in ics and "DTEND;VALUE=DATE:20261031" in ics
    assert "DTSTART:20261105T060000Z" in ics            # 11:30 IST = 06:00 UTC
    assert "TRIGGER:-PT900M" in ics and "TRIGGER:-PT60M" in ics
    assert ics.startswith("BEGIN:VCALENDAR") and ics.rstrip().endswith("END:VCALENDAR")


# ------------------------------------------------- after approval only
@pytest.fixture
def plan():
    return rem.plan_items([
        {"kind": "deadline", "title": "SDE-1", "company": "Acme", "date": "2026-10-30", "time": ""},
        {"kind": "interview", "title": "SDE-1", "company": "Acme", "date": "2026-11-05", "time": "11:30"}], TODAY, NOW)


def test_create_events_refuses_without_approval(plan):
    for flag in (False, None, "yes"):
        with pytest.raises(calendar_tool.CalendarError):
            rem.create_events("s", plan, flag)
    assert store.list_reminders("s") == []


def test_not_connected_falls_back_to_ics_and_records(plan, monkeypatch, tmp_path):
    monkeypatch.setattr(calendar_tool, "TOKEN_FILE", tmp_path / "none.json")
    out = rem.create_events("s", plan, True)
    assert {r["status"] for r in out["results"]} == {"ics only"} and "BEGIN:VCALENDAR" in out["ics"]
    assert len(store.list_reminders("s")) == len(plan)


def test_connected_creates_events_once_and_skips_duplicates(plan, monkeypatch):
    created = []
    monkeypatch.setattr(calendar_tool, "create_reminder_event", lambda ok, it: created.append(it["title"]) or f"ev{len(created)}")
    first = rem.create_events("s", plan, True)
    second = rem.create_events("s", plan, True)
    assert [r["status"] for r in first["results"]] == ["created"] * len(plan) and first["ics"] == ""
    assert [r["status"] for r in second["results"]] == ["already added"] * len(plan)
    assert len(created) == len(plan)
    assert {r["calendar_status"] for r in store.list_reminders("s")} == {"created"}


def test_unticked_items_are_not_added(plan, monkeypatch):
    created = []
    monkeypatch.setattr(calendar_tool, "create_reminder_event", lambda ok, it: created.append(it) or "x")
    plan[0]["add"] = False
    rem.create_events("s", plan, True)
    assert len(created) == len(plan) - 1


def test_invalid_item_is_skipped_not_sent(monkeypatch):
    monkeypatch.setattr(calendar_tool, "create_reminder_event", lambda ok, it: pytest.fail("must not be called"))
    out = rem.create_events("s", [{"kind": "interview", "date": "bad", "time": "10:00", "title": "t", "add": True}], True)
    assert out["results"][0]["status"].startswith("skipped")


# --------------------------------------------------- router + graph
def test_router_sends_dates_to_remind_and_practice_to_interview():
    assert router.heuristic_intent("remind me about my interview on 5 Nov") == "remind"
    assert router.heuristic_intent("my interview is on 5 Nov at 11am") == "remind"
    assert router.heuristic_intent("last date to apply is 30 Oct") == "remind"
    assert router.heuristic_intent("start a mock interview") == "interview"


def test_chat_remind_plans_but_never_touches_the_calendar(monkeypatch):
    from datetime import timedelta
    monkeypatch.setattr(calendar_tool, "create_reminder_event", lambda *a, **k: pytest.fail("calendar touched"))
    base = datetime.now(calendar_tool.IST).date()
    d1, d2 = (base + timedelta(days=20)).isoformat(), (base + timedelta(days=30)).isoformat()
    state = graph.run_turn({"user_message": f"Remind me: last date to apply {d1}. Interview on {d2} at 3 pm.",
                            "session_id": "s"})
    assert state["intent"] == "remind" and len(state["reminder_plan"]) == 3
    assert "Nothing is added" in state["final_response"]
    assert store.list_reminders("s") == []
