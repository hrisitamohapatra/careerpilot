"""Extra CRUD helpers (match results, drafts, job results, applications, interviews)."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .db import conn

APP_STATUSES = ["Saved", "Applied", "Interview", "Offer", "Rejected"]


# ------------------------------------------------------------------- match
def save_match(resume_id: int | None, jd_id: int | None, result: dict) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO match_results(resume_id, jd_id, overall_score, breakdown_json, matched_skills_json,"
            " missing_skills_json, created_at) VALUES(?,?,?,?,?,?,?)",
            (
                resume_id, jd_id, result["overall_score"], json.dumps(result["breakdown"]),
                json.dumps(result["matched_skills"]), json.dumps(result["missing_skills"]), time.time(),
            ),
        )
        return int(cur.lastrowid)


# ------------------------------------------------------------------ drafts
def save_draft(session_id: str, kind: str, subject: str, body: str, status: str = "draft") -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO generated_content(session_id, type, subject, body, status, idempotency_key, created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (session_id, kind, subject, body, status, uuid.uuid4().hex, time.time()),
        )
        return int(cur.lastrowid)


def claim_draft(draft_id: int) -> bool:
    """Atomically move a draft to 'sending'. False when it was already claimed or sent."""
    with conn() as c:
        cur = c.execute(
            "UPDATE generated_content SET status='sending' WHERE id=? AND status IN ('draft','failed')",
            (draft_id,),
        )
        return cur.rowcount == 1


def set_draft_status(draft_id: int, status: str) -> None:
    with conn() as c:
        c.execute("UPDATE generated_content SET status=? WHERE id=?", (status, draft_id))


def get_draft_status(draft_id: int) -> str | None:
    with conn() as c:
        row = c.execute("SELECT status FROM generated_content WHERE id=?", (draft_id,)).fetchone()
        return row["status"] if row else None


# ------------------------------------------------------------- job results
def save_job_results(session_id: str, ranked: list[dict]) -> None:
    with conn() as c:
        for r in ranked:
            j = r["job"]
            c.execute(
                "INSERT INTO job_results(session_id, source, title, company, location, url, score, created_at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (session_id, j["source"], j["title"], j["company"], j["location"], j["url"], r["score"], time.time()),
            )


# ------------------------------------------------------------ applications
def insert_application(session_id: str, job: dict, score: float | None, status: str,
                       applied_date: str, follow_up_date: str, draft_id: int | None) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO applications(session_id, job_title, company, source, url, match_score, status,"
            " applied_date, follow_up_date, calendar_event_id, calendar_status, draft_id)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                session_id, job.get("title", ""), job.get("company", ""), job.get("source", ""),
                job.get("url", ""), score, status, applied_date, follow_up_date, "", "none", draft_id,
            ),
        )
        return int(cur.lastrowid)


def set_application_calendar(app_id: int, event_id: str, status: str) -> None:
    with conn() as c:
        c.execute(
            "UPDATE applications SET calendar_event_id=?, calendar_status=? WHERE id=?",
            (event_id, status, app_id),
        )


def update_application_status(app_id: int, status: str) -> None:
    if status not in APP_STATUSES:
        return
    with conn() as c:
        c.execute("UPDATE applications SET status=? WHERE id=?", (status, app_id))


def list_applications(session_id: str) -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM applications WHERE session_id=? ORDER BY id DESC", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# --------------------------------------------------------------- reminders
def reminder_exists(session_id: str, key: str) -> bool:
    """True if this reminder was already added (created or saved as .ics) in this session."""
    if not key:
        return False
    with conn() as c:
        row = c.execute(
            "SELECT 1 FROM reminders WHERE session_id=? AND dedupe_key=?", (session_id, key)
        ).fetchone()
        return row is not None


def insert_reminder(session_id: str, item: dict, calendar_status: str, event_id: str = "") -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO reminders(session_id, kind, title, company, event_date, event_time, all_day,"
            " reminders_json, calendar_status, calendar_event_id, dedupe_key, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                session_id, item["kind"], item["title"], item.get("company", ""), item["date"], item.get("time", ""),
                1 if item.get("all_day") else 0, json.dumps(item.get("reminders_min", [])), calendar_status,
                event_id, item.get("key", ""), time.time(),
            ),
        )
        return int(cur.lastrowid)


def list_reminders(session_id: str) -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM reminders WHERE session_id=? ORDER BY event_date ASC, event_time ASC", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# --------------------------------------------------------------- interviews
def save_interview(session_id: str, resume_id: int | None, role: str, overall: float,
                   report: dict, turns: list[dict]) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO interview_sessions(session_id, resume_id, jd_id, role, overall_score, report_json, created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (session_id, resume_id, None, role, overall, json.dumps(report), time.time()),
        )
        sid = int(cur.lastrowid)
        for i, t in enumerate(turns):
            c.execute(
                "INSERT INTO interview_turns(interview_session_id, idx, question, answer, scores_json,"
                " feedback_json, is_followup) VALUES(?,?,?,?,?,?,?)",
                (
                    sid, i, t["question"], t["answer"], json.dumps(t["scores"]),
                    json.dumps(t["feedback"]), 1 if t.get("is_followup") else 0,
                ),
            )
        return sid
