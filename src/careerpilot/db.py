"""SQLite schema and CRUD. Every query uses parameter binding."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, created_at REAL);
CREATE TABLE IF NOT EXISTS resumes(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, filename TEXT, parsed_text TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS job_descriptions(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, title TEXT, company TEXT, text TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS match_results(id INTEGER PRIMARY KEY AUTOINCREMENT, resume_id INTEGER, jd_id INTEGER, overall_score REAL, breakdown_json TEXT, matched_skills_json TEXT, missing_skills_json TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS generated_content(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, type TEXT, subject TEXT, body TEXT, status TEXT, idempotency_key TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS job_results(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, source TEXT, title TEXT, company TEXT, location TEXT, url TEXT, score REAL, created_at REAL);
CREATE TABLE IF NOT EXISTS applications(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, job_title TEXT, company TEXT, source TEXT, url TEXT, match_score REAL, status TEXT, applied_date TEXT, follow_up_date TEXT, calendar_event_id TEXT, calendar_status TEXT, draft_id INTEGER);
CREATE TABLE IF NOT EXISTS interview_sessions(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, resume_id INTEGER, jd_id INTEGER, role TEXT, overall_score REAL, report_json TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS interview_turns(id INTEGER PRIMARY KEY AUTOINCREMENT, interview_session_id INTEGER, idx INTEGER, question TEXT, answer TEXT, scores_json TEXT, feedback_json TEXT, is_followup INTEGER);
CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, kind TEXT, title TEXT, company TEXT, event_date TEXT, event_time TEXT, all_day INTEGER, reminders_json TEXT, calendar_status TEXT, calendar_event_id TEXT, dedupe_key TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS api_cache(key TEXT PRIMARY KEY, value_json TEXT, created_at REAL);
"""


@contextmanager
def conn() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    with conn() as c:
        c.executescript(SCHEMA)


def new_session() -> str:
    init_db()
    sid = uuid.uuid4().hex
    with conn() as c:
        c.execute("INSERT INTO sessions(id, created_at) VALUES(?, ?)", (sid, time.time()))
    return sid


# ----------------------------------------------------------------- resumes
def save_resume(session_id: str, filename: str, text: str) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO resumes(session_id, filename, parsed_text, created_at) VALUES(?,?,?,?)",
            (session_id, filename, text, time.time()),
        )
        return int(cur.lastrowid)


def get_resume(resume_id: int) -> dict[str, Any] | None:
    with conn() as c:
        row = c.execute("SELECT * FROM resumes WHERE id=?", (resume_id,)).fetchone()
        return dict(row) if row else None


def save_jd(session_id: str, title: str, company: str, text: str) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO job_descriptions(session_id, title, company, text, created_at) VALUES(?,?,?,?,?)",
            (session_id, title, company, text, time.time()),
        )
        return int(cur.lastrowid)


# ------------------------------------------------------------------- cache
def cache_get(key: str, max_age_s: float) -> Any | None:
    with conn() as c:
        row = c.execute("SELECT value_json, created_at FROM api_cache WHERE key=?", (key,)).fetchone()
    if row and time.time() - row["created_at"] < max_age_s:
        return json.loads(row["value_json"])
    return None


def cache_set(key: str, value: Any) -> None:
    with conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO api_cache(key, value_json, created_at) VALUES(?,?,?)",
            (key, json.dumps(value), time.time()),
        )


# ------------------------------------------------------------ delete my data
def delete_session_data(session_id: str) -> None:
    with conn() as c:
        rids = [r["id"] for r in c.execute("SELECT id FROM resumes WHERE session_id=?", (session_id,))]
        for rid in rids:
            c.execute("DELETE FROM match_results WHERE resume_id=?", (rid,))
        isids = [r["id"] for r in c.execute("SELECT id FROM interview_sessions WHERE session_id=?", (session_id,))]
        for iid in isids:
            c.execute("DELETE FROM interview_turns WHERE interview_session_id=?", (iid,))
        for table in (
            "interview_sessions", "applications", "job_results",
            "generated_content", "job_descriptions", "resumes", "reminders",
        ):
            c.execute(f"DELETE FROM {table} WHERE session_id=?", (session_id,))  # table names are constants
        # cached skill profiles and match scores are derived from the resume, so they go too
        c.execute("DELETE FROM api_cache WHERE key LIKE ? OR key LIKE ?", ("profile:%", "match:%"))
