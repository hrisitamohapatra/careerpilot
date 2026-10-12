"""AGENTIC TASK 3: Adaptive Mock Interview (LangGraph, one user turn at a time).

plan_questions -> ask_question | evaluate_answer -> decide_next -> (followup | next_question | final_report)
"""
from __future__ import annotations

import random
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .. import config, llm, prompts, security, store
from ..schemas import AnswerEvaluation, FollowUp, InterviewQuestion, QuestionPlan, ReportExtras

BEHAVIORAL = [
    "Tell me about a time you worked in a team and disagreed with someone. How did you handle it?",
    "Describe a time you had to learn something new quickly to finish a project.",
    "Tell me about a mistake you made on a project and what you changed afterwards.",
    "Describe a time you handled a tight deadline. What did you cut and what did you protect?",
    "Tell me about a project you are proud of and what your own contribution was.",
]


class InterviewState(TypedDict, total=False):
    resume_text: str
    jd_text: str
    role: str
    missing_skills: list[str]
    answer: str
    session_id: str
    resume_id: int
    interview: dict
    last_eval: dict


def new_interview() -> dict:
    return {
        "status": "idle", "question_plan": [], "current_index": 0, "current_question": None,
        "followup_used": False, "history": [], "report": None,
    }


# ----------------------------------------------------------- pure decision
def decide(overall: float, followup_used: bool, index: int, total: int) -> str:
    """'followup' | 'next' | 'report'. Weak answer and no follow-up yet -> exactly one follow-up."""
    if overall < 5 and not followup_used:
        return "followup"
    return "next" if index + 1 < total else "report"


# ------------------------------------------------------------------ nodes
def _fallback_plan(state: InterviewState) -> list[InterviewQuestion]:
    qs = [
        InterviewQuestion(text="Walk me through the project on your resume you are most proud of. What did you build and how?", type="resume", topic="main project"),
        InterviewQuestion(text="Which technical skill on your resume are you strongest in? Give a concrete example of using it.", type="resume", topic="strongest skill"),
    ]
    for s in (state.get("missing_skills") or ["system design"])[:2]:
        qs.append(InterviewQuestion(text=f"This role uses {s}, which is not on your resume. How would you get productive in it in your first month?", type="skill_gap", topic=s))
    return qs


def plan_questions(state: InterviewState) -> dict:
    iv = new_interview()
    plan: list[InterviewQuestion] = []
    if llm.available():
        user = (
            f"{security.wrap('resume', state.get('resume_text', '')[:6000])}\n\n"
            f"{security.wrap('job', state.get('jd_text', '')[:4000] or 'No job description given. Use the target role: ' + state.get('role', ''))}\n\n"
            f"Skill gaps: {', '.join(state.get('missing_skills', [])[:8]) or 'none found'}"
        )
        try:
            plan = llm.structured(QuestionPlan, prompts.PLAN_Q_SYSTEM, user, tier="fast", temperature=0.4).questions[:4]
        except (llm.LLMUnavailable, ValueError):
            plan = []
    plan = plan or _fallback_plan(state)
    plan = plan[: config.INTERVIEW_QUESTIONS - 1]
    plan.append(InterviewQuestion(text=random.choice(BEHAVIORAL), type="behavioral", topic="behavioral"))
    iv["question_plan"] = [q.model_dump() for q in plan]
    iv["status"] = "asking"
    return {"interview": iv}


def ask_question(state: InterviewState) -> dict:
    iv = dict(state["interview"])
    if not iv.get("current_question"):
        iv["current_question"] = dict(iv["question_plan"][iv["current_index"]], is_followup=False)
    return {"interview": iv}


def _heuristic_eval(question: str, answer: str) -> AnswerEvaluation:
    words = len(answer.split())
    q_words = {w for w in question.lower().split() if len(w) > 4}
    overlap = sum(1 for w in q_words if w in answer.lower())
    base = min(9.0, 1.5 + words / 14 + 0.4 * overlap)
    base = round(max(0.0, min(10.0, base)), 1)
    n = int(round(base))
    return AnswerEvaluation(
        relevance=min(10, n + 1), depth=max(0, n - 1), clarity=n, examples=max(0, n - 2), overall=base,
        strengths=["Answered the question."] if words > 25 else [],
        weaknesses=["Too short or generic; add a concrete example and the result."] if words <= 40 else [],
        improved_sample_answer="Name the situation, what you did, which tools you used, and the result.",
        justification="Scored in code from answer length and topic words because the AI model was not available.",
    )


def evaluate_answer(state: InterviewState) -> dict:
    iv = dict(state["interview"])
    cq = iv["current_question"]
    answer = security.cap_chat(state.get("answer", ""))
    ev: AnswerEvaluation | None = None
    if llm.available():
        user = (
            f"Question: {cq['text']}\nTopic: {cq.get('topic', '')}\n"
            f"{security.wrap('resume', state.get('resume_text', '')[:4000])}\n"
            f"{security.wrap('user_text', answer)}"
        )
        try:
            ev = llm.structured(AnswerEvaluation, prompts.EVAL_ANSWER_SYSTEM, user, tier="strong", temperature=0.0)
        except (llm.LLMUnavailable, ValueError):
            ev = None
    ev = ev or _heuristic_eval(cq["text"], answer)
    turn = {
        "question": cq["text"], "answer": answer, "is_followup": bool(cq.get("is_followup")),
        "type": cq.get("type", ""), "topic": cq.get("topic", ""),
        "scores": {"relevance": ev.relevance, "depth": ev.depth, "clarity": ev.clarity,
                   "examples": ev.examples, "overall": ev.overall},
        "feedback": {"strengths": ev.strengths, "weaknesses": ev.weaknesses,
                     "improved_sample_answer": ev.improved_sample_answer, "justification": ev.justification},
    }
    iv["history"] = iv["history"] + [turn]
    return {"interview": iv, "last_eval": turn}


def decide_next(state: InterviewState) -> str:
    iv = state["interview"]
    overall = state["last_eval"]["scores"]["overall"]
    return decide(overall, iv["followup_used"], iv["current_index"], len(iv["question_plan"]))


def followup(state: InterviewState) -> dict:
    iv = dict(state["interview"])
    cq = iv["current_question"]
    text = f"Can you be more specific about {cq.get('topic') or 'that'}? Give one concrete example and the result."
    if llm.available():
        user = f"Question: {cq['text']}\n{security.wrap('user_text', state.get('answer', ''))}"
        try:
            text = llm.structured(FollowUp, prompts.FOLLOWUP_SYSTEM, user, tier="fast", temperature=0.3).question
        except (llm.LLMUnavailable, ValueError):
            pass
    iv["current_question"] = {"text": text, "type": cq.get("type", ""), "topic": cq.get("topic", ""), "is_followup": True}
    iv["followup_used"] = True
    return {"interview": iv}


def next_question(state: InterviewState) -> dict:
    iv = dict(state["interview"])
    iv["current_index"] += 1
    iv["current_question"] = dict(iv["question_plan"][iv["current_index"]], is_followup=False)
    iv["followup_used"] = False
    return {"interview": iv}


def final_report(state: InterviewState) -> dict:
    iv = dict(state["interview"])
    hist = iv["history"]
    # per-question score = best score among the question and its follow-up
    per_q, cur = [], None
    for t in hist:
        if not t["is_followup"]:
            cur = {"question": t["question"], "topic": t["topic"], "score": t["scores"]["overall"], "followup": False}
            per_q.append(cur)
        elif cur is not None:
            cur["score"] = max(cur["score"], t["scores"]["overall"])
            cur["followup"] = True
    overall = round(sum(q["score"] for q in per_q) / len(per_q), 1) if per_q else 0.0
    extras = ReportExtras(
        top_strengths=[s for t in hist for s in t["feedback"]["strengths"]][:3],
        top_weaknesses=[w for t in hist for w in t["feedback"]["weaknesses"]][:3],
        study_plan=[f"Practise explaining {s} with one real example." for s in (state.get("missing_skills") or [])[:4]]
        or ["Practise answers with the situation, action and result structure."],
    )
    if llm.available() and hist:
        summary = "\n".join(f"Q: {t['question']}\nScore: {t['scores']['overall']}\nWeak: {t['feedback']['weaknesses']}" for t in hist)
        user = security.wrap("context", summary) + f"\nSkill gaps: {', '.join(state.get('missing_skills', [])[:8])}"
        try:
            extras = llm.structured(ReportExtras, prompts.REPORT_SYSTEM, user, tier="fast", temperature=0.2)
        except (llm.LLMUnavailable, ValueError):
            pass
    report = {"overall": overall, "per_question": per_q, **extras.model_dump()}
    iv["report"] = report
    iv["status"] = "done"
    if state.get("session_id"):
        store.save_interview(state["session_id"], state.get("resume_id"), state.get("role", ""), overall, report, hist)
    return {"interview": iv}


def _entry(state: InterviewState) -> str:
    iv = state.get("interview") or {}
    return "evaluate_answer" if iv.get("status") == "asking" and state.get("answer") else "plan_questions"


def build_graph():
    g = StateGraph(InterviewState)
    for name, fn in [("plan_questions", plan_questions), ("ask_question", ask_question), ("evaluate_answer", evaluate_answer),
                     ("followup", followup), ("next_question", next_question), ("final_report", final_report)]:
        g.add_node(name, fn)
    g.add_conditional_edges(START, _entry, {"plan_questions": "plan_questions", "evaluate_answer": "evaluate_answer"})
    g.add_edge("plan_questions", "ask_question")
    g.add_conditional_edges(
        "evaluate_answer", decide_next,
        {"followup": "followup", "next": "next_question", "report": "final_report"},
    )
    g.add_edge("followup", "ask_question")
    g.add_edge("next_question", "ask_question")
    g.add_edge("ask_question", END)
    g.add_edge("final_report", END)
    return g.compile()


_GRAPH = None


def step(state: dict) -> dict:
    """Advance the interview by one user turn. `state` holds resume_text, jd_text, interview, answer..."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    state = dict(state)
    state.setdefault("interview", new_interview())
    return _GRAPH.invoke(state)
