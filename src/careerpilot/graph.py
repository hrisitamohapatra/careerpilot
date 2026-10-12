"""The main LangGraph: router -> gate (missing inputs) -> one task node -> END."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from . import db, llm, prompts, security, store
from .nodes import apply as apply_node_mod
from .nodes import improve, interview, jobs, match, qa, reminders, router
from .state import AgentState

NEED = {
    "resume": "Upload a resume first (sidebar), then ask again.",
    "jd": "Paste a job description in the sidebar first, then ask again.",
    "role": "Set a target role in the sidebar first, then ask again.",
    "job": "Pick a job in the Jobs tab first (click Apply on a listing), then ask again.",
}


# ------------------------------------------------------------------ nodes
def router_node(state: AgentState) -> dict:
    active = (state.get("interview") or {}).get("status") == "asking"
    return {"intent": router.route(state.get("user_message", ""), interview_active=active)}


def gate_node(state: AgentState) -> dict:
    intent = state.get("intent", "clarify")
    missing = ""
    if intent in {"qa", "match", "improve", "jobs", "apply", "interview"} and not state.get("resume_text"):
        missing = "resume"
    elif intent == "match" and not state.get("jd_text"):
        missing = "jd"
    elif intent == "jobs" and not state.get("target_role"):
        missing = "role"
    elif intent == "apply" and not state.get("selected_job"):
        missing = "job"
    out: dict = {"missing": missing}
    if missing:
        out["final_response"] = NEED[missing]
    return out


def _after_gate(state: AgentState) -> str:
    if state.get("missing"):
        return END
    return {
        "qa": "qa", "match": "match", "improve": "improve", "jobs": "jobs", "apply": "apply",
        "interview": "interview", "remind": "remind", "smalltalk": "smalltalk",
    }.get(state.get("intent", ""), "clarify")


def qa_node(state: AgentState) -> dict:
    try:
        res = qa.answer_question(state["resume_id"], state["user_message"])
    except llm.LLMUnavailable as e:
        return {"final_response": str(e), "sources": []}
    return {"final_response": res["answer"], "sources": res["sources"]}


def match_node(state: AgentState) -> dict:
    res = match.compute_match(state["resume_text"], state["jd_text"], use_llm=llm.available())
    jd_id = db.save_jd(state.get("session_id", ""), "Pasted job description", "", state["jd_text"][:8000])
    store.save_match(state.get("resume_id"), jd_id, res.model_dump())
    top = ", ".join(res.missing_skills[:5]) or "none"
    return {
        "last_match": res.model_dump(),
        "final_response": f"Match score: {res.overall_score:.0f}/100. Missing skills: {top}. Details are in the Match tab.",
    }


def improve_node(state: AgentState) -> dict:
    msg = state.get("user_message", "").lower()
    lm = state.get("last_match") or {}
    try:
        if "bullet" in msg or "rewrite" in msg:
            items = improve.rewrite_bullets(state["resume_text"], state.get("jd_text", ""), lm.get("missing_skills"))
            lines = []
            for it in items:
                flag = " (add a real number where you see [add number])" if it.needs_metric else ""
                lines.append(f"Before: {it.original}\nAfter: {it.improved}\nWhy: {it.reason}{flag}")
            return {"final_response": "\n\n".join(lines) or "I could not find bullets to improve."}
    except llm.LLMUnavailable as e:
        return {"final_response": str(e)}
    job = state.get("selected_job", {}).get("job") if state.get("selected_job") else None
    if not job and state.get("jd_text"):
        job = {"title": "the role", "company": "your company", "description": state["jd_text"]}
    if not job:
        return {"final_response": "Select a job in the Jobs tab or paste a job description first, then ask for a cover letter."}
    sel = state.get("selected_job") or {}
    matched = sel.get("matched") or lm.get("matched_skills", [])
    missing = sel.get("missing") or lm.get("missing_skills", [])
    draft, _ = improve.write_documents(state["resume_text"], job, matched, missing)
    store.save_draft(state.get("session_id", ""), "cover_letter", draft.subject, draft.cover_letter)
    return {"final_response": f"Subject: {draft.subject}\n\n{draft.email_body}\n\nCover letter:\n\n{draft.cover_letter}"}


def jobs_node(state: AgentState) -> dict:
    inputs = {
        "resume_text": state["resume_text"], "target_role": state["target_role"], "city": state.get("city", ""),
        "include_remote": state.get("include_remote", False), "enabled_sources": state.get("enabled_sources", []),
        "session_id": state.get("session_id", ""),
    }
    final = jobs.run_job_agent(inputs)
    ranked = final.get("ranked", [])
    note = " Sample data is shown because no live source returned results." if final.get("used_sample") else ""
    return {
        "jobs": ranked, "job_log": final.get("rounds", []), "job_statuses": final.get("statuses", {}),
        "used_sample": final.get("used_sample", False),
        "final_response": f"Found {len(ranked)} ranked jobs for {state['target_role']}. See the Jobs tab.{note}",
    }


def apply_node(state: AgentState) -> dict:
    sel = state["selected_job"]
    draft = apply_node_mod.draft_for_job(state.get("session_id", ""), state["resume_text"], sel)
    return {
        "draft": draft, "pending_approval": True,
        "final_response": "Your draft is ready. Review it and approve in the Apply tab. Nothing is sent until you click Approve and Send.",
    }


def interview_node(state: AgentState) -> dict:
    iv = state.get("interview") or interview.new_interview()
    lm = state.get("last_match") or {}
    sel = state.get("selected_job") or {}
    payload = {
        "resume_text": state["resume_text"], "jd_text": state.get("jd_text", ""), "role": state.get("target_role", ""),
        "missing_skills": sel.get("missing") or lm.get("missing_skills", []), "session_id": state.get("session_id", ""),
        "resume_id": state.get("resume_id"), "interview": iv,
    }
    if iv.get("status") == "asking":
        payload["answer"] = state.get("user_message", "")
    out = interview.step(payload)
    iv2 = out["interview"]
    if iv2["status"] == "done":
        text = f"Interview finished. Overall score: {iv2['report']['overall']}/10. See the Interview tab for the report."
    else:
        q = iv2["current_question"]
        prefix = ""
        if out.get("last_eval"):
            prefix = f"Score for your last answer: {out['last_eval']['scores']['overall']}/10.\n\n"
        label = "Follow-up: " if q.get("is_followup") else f"Question {iv2['current_index'] + 1} of {len(iv2['question_plan'])}: "
        text = prefix + label + q["text"]
    return {"interview": iv2, "final_response": text}


def remind_node(state: AgentState) -> dict:
    """Find dates in the message (or the pasted job description) and plan reminders. Nothing is created here."""
    sel = (state.get("selected_job") or {}).get("job", {})
    role, company = sel.get("title", ""), sel.get("company", "")
    use_llm = llm.available()
    res = reminders.run_reminder_agent(state.get("user_message", ""), company, role, use_llm=use_llm)
    if not res["plan"] and state.get("jd_text"):
        res = reminders.run_reminder_agent(state["jd_text"], company, role, use_llm=use_llm)
    plan = res["plan"]
    if not plan:
        return {"reminder_plan": [], "reminder_log": res["log"],
                "final_response": "I could not find a date to remind you about. Include the date, for example: "
                                  "interview on 5 Nov 2026 at 11 am, or last date to apply 30 Oct 2026."}
    n = len(plan)
    return {"reminder_plan": plan, "reminder_log": res["log"],
            "final_response": f"I planned {n} calendar entr{'y' if n == 1 else 'ies'}. Open the Reminders tab to review "
                              "them. Nothing is added to your calendar until you approve."}


def smalltalk_node(state: AgentState) -> dict:
    return {"final_response": prompts.HELP_TEXT}


def clarify_node(state: AgentState) -> dict:
    return {"final_response": "I am not sure what you need. " + prompts.HELP_TEXT}


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("router", router_node)
    g.add_node("gate", gate_node)
    for name, fn in [
        ("qa", qa_node), ("match", match_node), ("improve", improve_node), ("jobs", jobs_node),
        ("apply", apply_node), ("interview", interview_node), ("remind", remind_node),
        ("smalltalk", smalltalk_node), ("clarify", clarify_node),
    ]:
        g.add_node(name, fn)
        g.add_edge(name, END)
    g.add_edge(START, "router")
    g.add_edge("router", "gate")
    g.add_conditional_edges("gate", _after_gate, {
        "qa": "qa", "match": "match", "improve": "improve", "jobs": "jobs", "apply": "apply",
        "interview": "interview", "remind": "remind", "smalltalk": "smalltalk", "clarify": "clarify", END: END,
    })
    return g.compile()


_GRAPH = None


def run_turn(state: dict) -> dict:
    """One chat turn through the router graph. Returns the updated state."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    state = dict(state)
    state["user_message"] = security.cap_chat(state.get("user_message", ""))
    state["sources"] = []
    return _GRAPH.invoke(state)
