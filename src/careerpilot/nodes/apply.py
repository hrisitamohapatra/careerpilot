"""AGENTIC TASK 2: Apply and Track.

draft -> (human review + approval in the UI) -> send email -> log to tracker -> calendar event.
The model never picks recipients, dates or links; those come from validated UI fields.
"""
from __future__ import annotations

from datetime import date, timedelta

from .. import security, store
from ..tools import calendar_tool, email_tool
from . import improve


def _followup_item(job: dict, follow_up: date) -> dict:
    """The follow-up event as a reminders-list row, so it shows up in the Reminders tab."""
    return {
        "kind": "follow_up", "title": f"Follow up: {job.get('title', '')} at {job.get('company', '')}"[:120],
        "company": job.get("company", ""), "date": follow_up.isoformat(), "time": "10:00", "all_day": False,
        "reminders_min": [30], "key": "",
    }


def default_follow_up() -> date:
    return date.today() + timedelta(days=7)


def draft_for_job(session_id: str, resume_text: str, ranked_job: dict) -> dict:
    """Draft the email + cover letter for a ranked job (uses its matched / missing skills)."""
    job = ranked_job["job"]
    draft, used_ai = improve.write_documents(resume_text, job, ranked_job.get("matched", []), ranked_job.get("missing", []))
    draft_id = store.save_draft(session_id, "recruiter_email", draft.subject, draft.email_body)
    store.save_draft(session_id, "cover_letter", draft.subject, draft.cover_letter)
    return {
        "draft_id": draft_id, "subject": draft.subject, "body": draft.email_body,
        "cover_letter": draft.cover_letter, "used_ai": used_ai, "status": "draft",
    }


def save_as_draft_only(session_id: str, ranked_job: dict, draft_id: int, follow_up: date) -> int:
    """No SMTP: still log the application, as Saved."""
    return store.insert_application(
        session_id, ranked_job["job"], ranked_job.get("score"), "Saved",
        date.today().isoformat(), follow_up.isoformat(), draft_id,
    )


def execute_approved(session_id: str, ranked_job: dict, draft_id: int, recipient: str, subject: str,
                     body: str, follow_up: date, limiter: security.SendLimiter) -> dict:
    """Run after the user clicks Approve and Send. Order: email, tracker, calendar. Runs once per draft."""
    result = {"email": "not sent", "application_id": None, "calendar": "none", "ics": "", "error": ""}
    if not store.claim_draft(draft_id):
        result["error"] = "This application was already handled. Check the Tracker tab."
        return result
    job = ranked_job["job"]
    try:
        email_tool.send_email(recipient, subject, body, approved=True, limiter=limiter)
        result["email"] = "sent"
    except email_tool.EmailNotConfigured:
        # friendly fallback: keep as Saved, user can download the text
        store.set_draft_status(draft_id, "draft")
        result["email"] = "smtp missing"
        result["application_id"] = save_as_draft_only(session_id, ranked_job, draft_id, follow_up)
        return result
    except (email_tool.EmailError, security.ValidationError) as e:
        store.set_draft_status(draft_id, "failed")
        result["error"] = str(e)
        return result

    store.set_draft_status(draft_id, "sent")
    app_id = store.insert_application(
        session_id, job, ranked_job.get("score"), "Applied",
        date.today().isoformat(), follow_up.isoformat(), draft_id,
    )
    result["application_id"] = app_id
    try:
        event_id = calendar_tool.create_followup_event(
            True, job.get("title", ""), job.get("company", ""), job.get("url", ""),
            ranked_job.get("score"), follow_up,
        )
        store.set_application_calendar(app_id, event_id, "created")
        store.insert_reminder(session_id, _followup_item(job, follow_up), "created", event_id)
        result["calendar"] = "created"
    except calendar_tool.CalendarError:
        result["ics"] = calendar_tool.build_ics(
            job.get("title", ""), job.get("company", ""), job.get("url", ""), ranked_job.get("score"), follow_up
        )
        store.set_application_calendar(app_id, "", "ics only")
        store.insert_reminder(session_id, _followup_item(job, follow_up), "ics only")
        result["calendar"] = "ics only"
    return result
