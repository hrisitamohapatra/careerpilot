"""Router: picks an intent only. It never chooses recipients, dates, links or actions."""
from __future__ import annotations

import re

from .. import llm, prompts, security
from ..schemas import RouterOut

_RULES = [
    ("remind", r"\b(remind|reminders?|calendar|deadline|last date|closing date|closes on|add to my calendar)\b|\binterview (is |was )?(on|at|scheduled)\b"),
    ("interview", r"\binterview|mock\b"),
    ("jobs", r"\b(find|search|look for|show|list)\b.*\b(jobs?|openings?|roles?|listings?|vacanc)|\bjob search\b"),
    ("improve", r"\b(rewrite|improve|bullet|cover letter|recruiter email|draft an? email|polish)\b"),
    ("apply", r"\bapply\b|\bapplication\b"),
    ("match", r"\b(match|score|fit|compare|ats)\b"),
    ("smalltalk", r"^(hi|hello|hey|thanks|thank you|ok|okay|namaste)\b"),
]


def heuristic_intent(message: str) -> str:
    low = message.lower().strip()
    for intent, pat in _RULES:
        if re.search(pat, low):
            return intent
    return "qa" if low else "clarify"


def route(message: str, interview_active: bool = False) -> str:
    """Return one intent. While an interview is running, answers go to the interview node."""
    if interview_active:
        return "interview"
    message = security.cap_chat(message)
    if not message:
        return "clarify"
    if llm.available():
        try:
            out = llm.structured(RouterOut, prompts.ROUTER_SYSTEM, security.wrap("user_text", message), tier="fast")
            return out.intent
        except (llm.LLMUnavailable, ValueError):
            pass
    return heuristic_intent(message)
