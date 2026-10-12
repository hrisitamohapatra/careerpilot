"""AGENTIC TASK 1: Job Search and Rank.

plan_keywords -> fetch_jobs -> evaluate_results -> (refine + refetch, max 2 loops) -> score_and_rank
"""
from __future__ import annotations

import operator
import re
from typing import Annotated, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from .. import config, llm, prompts, security, store
from ..schemas import EvalDecision, Job, KeywordPlan
from ..tools.job_sources import aggregator
from . import match

STOP = {"and", "for", "the", "with", "jobs", "job", "role", "roles", "senior", "junior", "sde"}
MIN_RELEVANT = 3
TOP_N = 8


class JobsState(TypedDict, total=False):
    resume_text: str
    target_role: str
    city: str
    include_remote: bool
    enabled_sources: list[str]
    session_id: str
    queries: list[str]
    tried: list[str]
    pool: dict            # dedupe-key string -> Job dict
    statuses: dict
    used_sample: bool
    loops: int
    need_more: bool
    rounds: Annotated[list, operator.add]
    ranked: list


# ------------------------------------------------------------- relevance
GENERIC = {"engineer", "developer", "software", "programmer", "intern", "fresher", "associate", "executive", "specialist", "trainee"}


def role_tokens(role: str) -> set[str]:
    return {t for t in re.findall(r"[a-z+#.]{3,}", (role or "").lower()) if t not in STOP}


def relevance(job: Job, role: str) -> float:
    """0..1. Distinctive words in the role ('backend', 'data') count; generic ones ('engineer') only
    count when the role has nothing else, so an ML Engineer is not a match for a Backend Engineer."""
    toks = role_tokens(role)
    if not toks:
        return 1.0
    key = {t for t in toks if t not in GENERIC} or toks
    blob = f"{job.title} {job.description[:300]}".lower()
    title = job.title.lower()
    hit = sum(1 for t in key if t in blob)
    bonus = 0.1 if any(t in title for t in key) else 0
    return min(1.0, hit / len(key) + bonus)


def is_relevant(job: Job, role: str) -> bool:
    return relevance(job, role) >= 0.5


# ------------------------------------------------------------------ nodes
def _fallback_queries(role: str) -> list[str]:
    role = (role or "software engineer").strip()
    return [role, f"{role} fresher", f"{role} developer"][:3]


def plan_keywords(state: JobsState) -> dict:
    role, city = state.get("target_role", ""), state.get("city", "")
    queries: list[str] = []
    if llm.available():
        user = (
            f"Target role: {role}\nCity: {city}\n"
            f"{security.wrap('resume', state.get('resume_text', '')[:3500])}"
        )
        try:
            queries = llm.structured(KeywordPlan, prompts.KEYWORDS_SYSTEM, user, tier="fast").queries
        except (llm.LLMUnavailable, ValueError):
            queries = []
    queries = [q[:80] for q in (queries or _fallback_queries(role))][:4]
    return {"queries": queries, "tried": [], "pool": {}, "statuses": {}, "loops": 0, "used_sample": False}


def fetch_jobs(state: JobsState) -> dict:
    pool = dict(state.get("pool", {}))
    statuses = dict(state.get("statuses", {}))
    used_sample = state.get("used_sample", False)
    queries = state.get("queries", [])
    live: set[str] = set()
    for q in queries:
        out = aggregator.search(q, state.get("city", ""), state.get("enabled_sources", []), state.get("include_remote", False))
        statuses.update(out.statuses)
        used_sample = used_sample or out.used_sample
        live |= {s for s, v in out.statuses.items() if s != aggregator.SAMPLE_NAME and v.endswith("listings")}
        for j in out.jobs:
            pool.setdefault("|".join(j.dedupe_key()), j.model_dump())
    role = state.get("target_role", "")
    relevant = [j for j in pool.values() if is_relevant(Job(**j), role)]
    where = f"across {len(live)} live source(s)" if live else "in the sample listings (no live source available)"
    line = (
        f"Round {state.get('loops', 0) + 1}: searched {', '.join(repr(q) for q in queries)} "
        f"{where}, found {len(relevant)} relevant"
    )
    return {
        "pool": pool, "statuses": statuses, "used_sample": used_sample,
        "tried": state.get("tried", []) + queries, "rounds": [line],
    }


def _refine_fallback(state: JobsState) -> list[str]:
    tried = {q.lower() for q in state.get("tried", [])}
    role = state.get("target_role", "")
    cands = [f"{role} engineer", f"{role} intern", f"software {role}", "software engineer", "developer"]
    return [c[:80] for c in cands if c.lower() not in tried][:2] or ["software developer"]


def evaluate_results(state: JobsState) -> dict:
    """Decide whether results are good enough. If not, propose DIFFERENT keywords and loop."""
    role = state.get("target_role", "")
    pool = [Job(**j) for j in state.get("pool", {}).values()]
    relevant = [j for j in pool if is_relevant(j, role)]
    loops = state.get("loops", 0)
    if len(relevant) >= MIN_RELEVANT or loops >= config.MAX_JOB_REFINE_LOOPS:
        return {"need_more": False}

    new_q: list[str] = []
    suggest_remote = False
    if llm.available():
        titles = "; ".join(j.title for j in pool[:25]) or "(none)"
        user = (
            f"Target role: {role}\nQueries tried: {state.get('tried', [])}\n"
            f"Relevant listings so far: {len(relevant)}\n{security.wrap('context', titles)}"
        )
        try:
            d = llm.structured(EvalDecision, prompts.EVAL_SYSTEM, user, tier="fast")
            new_q, suggest_remote = d.new_queries, d.suggest_remote
        except (llm.LLMUnavailable, ValueError):
            pass
    tried = {q.lower() for q in state.get("tried", [])}
    new_q = [q[:80] for q in new_q if q.strip() and q.lower() not in tried][:3] or _refine_fallback(state)
    note = f"Not enough relevant listings ({len(relevant)}). Trying: {', '.join(repr(q) for q in new_q)}"
    if suggest_remote and not state.get("include_remote"):
        note += ". Tip: turn on remote roles to widen the search."
    return {"need_more": True, "queries": new_q, "loops": loops + 1, "rounds": [note]}


def score_and_rank(state: JobsState) -> dict:
    role = state.get("target_role", "")
    jobs = [Job(**j) for j in state.get("pool", {}).values()]
    pool = sorted(jobs, key=lambda j: relevance(j, role), reverse=True)
    relevant = [j for j in pool if is_relevant(j, role)]
    used_sample = state.get("used_sample", False)
    if not relevant:
        # live sources gave nothing relevant: fall back to the bundled sample data
        sample = aggregator.search_sample(role or "software engineer", state.get("city", ""))
        pool = sample or aggregator.load_sample()
        relevant = [j for j in pool if is_relevant(j, role)] or pool
        used_sample = True
        statuses = dict(state.get("statuses", {}))
        statuses[aggregator.SAMPLE_NAME] = f"{len(relevant)} listings"
    else:
        statuses = state.get("statuses", {})
    top = relevant[:TOP_N]
    ranked = []
    use_llm = llm.available()
    for j in top:
        text = f"{j.title} at {j.company}. {j.description}"
        m = match.compute_match(state.get("resume_text", ""), text, use_llm=use_llm)
        ranked.append({
            "job": j.model_dump(), "score": m.overall_score, "matched": m.matched_skills,
            "missing": m.missing_skills, "breakdown": [c.model_dump() for c in m.breakdown],
        })
    ranked.sort(key=lambda r: r["score"], reverse=True)
    if state.get("session_id"):
        store.save_job_results(state["session_id"], ranked)
    return {"ranked": ranked, "used_sample": used_sample, "statuses": statuses}


def _after_eval(state: JobsState) -> str:
    return "fetch_jobs" if state.get("need_more") else "score_and_rank"


def build_graph():
    g = StateGraph(JobsState)
    g.add_node("plan_keywords", plan_keywords)
    g.add_node("fetch_jobs", fetch_jobs)
    g.add_node("evaluate_results", evaluate_results)
    g.add_node("score_and_rank", score_and_rank)
    g.add_edge(START, "plan_keywords")
    g.add_edge("plan_keywords", "fetch_jobs")
    g.add_edge("fetch_jobs", "evaluate_results")
    g.add_conditional_edges("evaluate_results", _after_eval, {"fetch_jobs": "fetch_jobs", "score_and_rank": "score_and_rank"})
    g.add_edge("score_and_rank", END)
    return g.compile()


_GRAPH = None


def run_job_agent(inputs: dict, on_update: Callable[[str, dict], None] | None = None) -> dict:
    """Run the agent; call on_update(node_name, update) after each step (for live UI). Returns final state."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    final: dict = dict(inputs)
    final["rounds"] = []
    for chunk in _GRAPH.stream(inputs, stream_mode="updates"):
        for node, update in chunk.items():
            for k, v in update.items():
                if k == "rounds":
                    final["rounds"] = final.get("rounds", []) + v
                else:
                    final[k] = v
            if on_update:
                on_update(node, update)
    return final
