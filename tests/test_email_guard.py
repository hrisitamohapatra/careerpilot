from datetime import date

import pytest

from careerpilot import config, security, store
from careerpilot.nodes import apply as apply_mod
from careerpilot.tools import calendar_tool, email_tool
from careerpilot.security import ValidationError


class FakeSMTP:
    sent = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, u, p):
        pass

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


@pytest.fixture
def smtp(monkeypatch):
    monkeypatch.setenv("SMTP_USER", "me@gmail.com")
    monkeypatch.setenv("SMTP_APP_PASSWORD", "pw")
    monkeypatch.setattr(email_tool.smtplib, "SMTP_SSL", FakeSMTP)
    FakeSMTP.sent = []


@pytest.mark.parametrize("flag", [False, None, 1, "yes", "True"])
def test_refuses_without_approved_true(smtp, flag):
    with pytest.raises(email_tool.EmailError):
        email_tool.send_email("a@b.com", "Hi", "Body", approved=flag)
    assert FakeSMTP.sent == []


@pytest.mark.parametrize("to,subj", [
    ("a@b.com\nBcc: x@y.com", "Hi"), ("a@b.com", "Hi\r\nBcc: x@y.com"), ("a@b.com%0aBcc:x@y.com", "Hi"),
    ("a@b.com,c@d.com", "Hi"), ("not-an-email", "Hi"),
])
def test_header_injection_rejected(smtp, to, subj):
    with pytest.raises(ValidationError):
        email_tool.send_email(to, subj, "Body", approved=True)
    assert FakeSMTP.sent == []


def test_limits(smtp):
    with pytest.raises(ValidationError):
        email_tool.send_email("a@b.com", "x" * 151, "Body", approved=True)
    with pytest.raises(ValidationError):
        email_tool.send_email("a@b.com", "Hi", "x" * 5001, approved=True)


def test_send_ok_uses_configured_sender_and_plain_text(smtp):
    lim = security.SendLimiter()
    email_tool.send_email("a@b.com", "Hi", "Body", approved=True, limiter=lim)
    msg = FakeSMTP.sent[0]
    assert msg["From"] == "me@gmail.com" and msg["To"] == "a@b.com"
    assert msg.get_content_type() == "text/plain"
    assert lim.count == 1


def test_rate_limit_five_per_session(smtp):
    lim = security.SendLimiter()
    for _ in range(5):
        email_tool.send_email("a@b.com", "Hi", "Body", approved=True, limiter=lim)
    with pytest.raises(ValidationError):
        email_tool.send_email("a@b.com", "Hi", "Body", approved=True, limiter=lim)


def test_missing_smtp_is_friendly():
    with pytest.raises(email_tool.EmailNotConfigured):
        email_tool.send_email("a@b.com", "Hi", "Body", approved=True)


def test_calendar_refuses_without_approval():
    with pytest.raises(calendar_tool.CalendarError):
        calendar_tool.create_followup_event(False, "SDE", "Acme", "https://x.com", 80, date(2026, 10, 20))


def test_calendar_not_connected_without_token(monkeypatch, tmp_path):
    monkeypatch.setattr(calendar_tool, "TOKEN_FILE", tmp_path / "nope.json")
    with pytest.raises(calendar_tool.CalendarNotConnected):
        calendar_tool.create_followup_event(True, "SDE", "Acme", "https://x.com", 80, date(2026, 10, 20))


def test_event_fields_and_ics():
    f = calendar_tool.event_fields("SDE\nIntern", "Acme", "https://x.com/j", 82.0, date(2026, 10, 20))
    assert f["summary"] == "Follow up: SDE Intern at Acme"
    assert f["start"]["dateTime"] == "2026-10-20T10:00:00" and f["start"]["timeZone"] == "Asia/Kolkata"
    assert f["reminders"]["overrides"][0]["method"] == "popup"
    ics = calendar_tool.build_ics("SDE", "Acme", "https://x.com/j", 82.0, date(2026, 10, 20))
    assert "DTSTART:20261020T043000Z" in ics and ics.startswith("BEGIN:VCALENDAR")


def test_apply_runs_once_even_on_double_click(smtp, monkeypatch, tmp_path):
    monkeypatch.setattr(calendar_tool, "TOKEN_FILE", tmp_path / "nope.json")
    job = {"job": {"title": "SDE", "company": "Acme", "source": "Adzuna", "url": "https://x.com"}, "score": 77}
    d = store.save_draft("s1", "recruiter_email", "Hi", "Body")
    lim = security.SendLimiter()
    r1 = apply_mod.execute_approved("s1", job, d, "a@b.com", "Hi", "Body", date(2026, 10, 20), lim)
    r2 = apply_mod.execute_approved("s1", job, d, "a@b.com", "Hi", "Body", date(2026, 10, 20), lim)
    assert r1["email"] == "sent" and r1["calendar"] == "ics only"
    assert r2["error"] and len(FakeSMTP.sent) == 1
    apps = store.list_applications("s1")
    assert len(apps) == 1 and apps[0]["status"] == "Applied" and apps[0]["calendar_status"] == "ics only"


def test_no_smtp_logs_saved(monkeypatch):
    job = {"job": {"title": "SDE", "company": "Acme", "source": "Adzuna", "url": ""}, "score": 50}
    d = store.save_draft("s2", "recruiter_email", "Hi", "Body")
    r = apply_mod.execute_approved("s2", job, d, "a@b.com", "Hi", "Body", date(2026, 10, 20), security.SendLimiter())
    assert r["email"] == "smtp missing"
    assert store.list_applications("s2")[0]["status"] == "Saved"
