"""Headless UI test: the app boots, shows the empty states, and renders without exceptions."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_app_boots_with_empty_state():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert [o.split(": ")[-1] for o in at.radio(key="nav").options] == ["Dashboard", "My Profile", "Workspace", "Reminders", "Interview"]
    assert any("Welcome back" in m.value for m in at.markdown)


def test_pages_without_a_resume_show_the_empty_state():
    at = AppTest.from_file(APP, default_timeout=30).run()
    for page in ("Workspace", "Interview"):
        at.radio(key="nav").set_value(page).run()
        assert not at.exception
        assert any("Upload a resume to get started" in i.value for i in at.info)


def test_pasted_resume_loads_and_jobs_run_on_sample(monkeypatch):
    from careerpilot import vectorstore

    monkeypatch.setattr(vectorstore, "index_resume", lambda rid, chunks: None)
    at = AppTest.from_file(APP, default_timeout=60).run()
    resume = (Path(__file__).resolve().parents[1] / "data" / "samples" / "resume_backend.txt").read_text(encoding="utf-8")
    at.radio(key="nav").set_value("My Profile").run()
    at.text_area(key="profile_resume").set_value(resume)
    at.text_input(key="target_role").set_value("Backend Engineer")
    at.button(key="save_profile").click().run()
    assert not at.exception
    assert at.session_state["resume_id"]
    at.radio(key="nav").set_value("Workspace").run()
    at.radio(key="ws").set_value("Jobs").run()
    assert not at.exception
    jobs_btn = [b for b in at.button if b.label == "Find jobs"]
    assert jobs_btn and not jobs_btn[0].disabled   # role survived the page change
    jobs_btn[0].click().run()
    assert not at.exception
    assert any("sample listings" in w.value for w in at.warning)


def test_reminders_tab_plans_then_adds_only_after_approval(monkeypatch):
    from datetime import datetime, timedelta

    from careerpilot import store
    from careerpilot.tools import calendar_tool

    monkeypatch.setattr(calendar_tool, "TOKEN_FILE", Path("/nonexistent/token.json"))
    base = datetime.now(calendar_tool.IST).date()
    d1, d2 = (base + timedelta(days=15)).isoformat(), (base + timedelta(days=25)).isoformat()
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.radio(key="nav").set_value("Reminders").run()
    at.text_area(key="remind_text").set_value(f"Last date to apply: {d1}. Interview on {d2} at 11 am.")
    [b for b in at.button if b.label == "Find dates"][0].click().run()
    assert not at.exception
    approve = [b for b in at.button if b.label == "Approve and add to calendar"]
    assert approve, "review screen should be shown"
    assert store.list_reminders(at.session_state["session_id"]) == []   # nothing added before approval
    approve[0].click().run()
    assert not at.exception
    rows = store.list_reminders(at.session_state["session_id"])
    assert len(rows) == 3 and {r["calendar_status"] for r in rows} == {"ics only"}
