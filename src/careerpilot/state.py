"""Shared LangGraph state."""
from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    messages: list[dict]          # [{role, content}]
    user_message: str
    session_id: str
    resume_id: int
    resume_text: str
    target_role: str
    city: str
    include_remote: bool
    enabled_sources: list[str]
    jd_text: str
    intent: str
    missing: str                  # what input is missing, if any
    last_match: dict | None
    jobs: list[dict]              # ranked list
    job_log: list[str]
    job_statuses: dict
    used_sample: bool
    selected_job: dict | None
    draft: dict | None            # subject, body, recipient, status ...
    pending_approval: bool
    interview: dict
    reminder_plan: list[dict]     # planned calendar entries awaiting approval
    reminder_log: list[str]
    sources: list[Any]            # QA snippets [(section, text)]
    final_response: str
