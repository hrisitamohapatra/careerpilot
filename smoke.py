"""Headless end-to-end check, no UI:  python smoke.py

resume -> QA (if the embedding model is available) -> match -> job search (sample data if no keys)
-> draft (nothing is sent, no calendar event) -> a 2-question mock interview.
Uses a throwaway database, so it never touches your real data.
"""
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="careerpilot_smoke_")
os.environ["CAREERPILOT_DB"] = str(Path(_tmp) / "smoke.db")
os.environ["CAREERPILOT_CHROMA"] = str(Path(_tmp) / "chroma")
sys.path.insert(0, str(Path(__file__).parent / "src"))

from careerpilot import config, db, llm, parsing, vectorstore  # noqa: E402
from careerpilot.nodes import apply, interview, jobs, match, qa, reminders  # noqa: E402

SAMPLES = config.DATA_DIR / "samples"


def step(msg: str) -> None:
    print(f"\n== {msg}")


def main() -> int:
    print("AI model:", "Groq key found" if llm.available() else "no GROQ_API_KEY (using code-only fallbacks)")
    sid = db.new_session()
    resume = (SAMPLES / "resume_backend.txt").read_text(encoding="utf-8")
    jd = (SAMPLES / "jd_backend.txt").read_text(encoding="utf-8")
    rid = db.save_resume(sid, "sample", resume)

    step("1. Resume QA")
    try:
        vectorstore.index_resume(rid, parsing.split_sections(resume))
        if llm.available():
            res = qa.answer_question(rid, "What are my top skills?")
            print("Answer:", res["answer"][:200])
            print("Sections cited from:", sorted({s for s, _ in res["sources"]}))
        else:
            print("Indexed OK. Set GROQ_API_KEY to see answers.")
    except Exception as e:  # noqa: BLE001
        print("Skipped (embedding model not reachable):", type(e).__name__)

    step("2. JD match")
    m = match.compute_match(resume, jd, use_llm=llm.available())
    print(f"Overall {m.overall_score}/100")
    for c in m.breakdown:
        print(f"  {c.name}: {c.score:.0f} (weight {c.weight})")
    print("Missing:", ", ".join(m.missing_skills) or "none")

    step("3. Job search and rank")
    final = jobs.run_job_agent({
        "resume_text": resume, "target_role": "Backend Engineer", "city": "Bengaluru",
        "include_remote": False, "enabled_sources": ["Adzuna", "Jooble"], "session_id": sid,
    })
    for line in final["rounds"]:
        print(" ", line)
    print("Sources:", final["statuses"], "| sample data:", final["used_sample"])
    for r in final["ranked"][:3]:
        print(f"  {r['score']:.0f}  {r['job']['title']} at {r['job']['company']} (via {r['job']['source']})")

    step("4. Draft (nothing is sent)")
    d = apply.draft_for_job(sid, resume, final["ranked"][0])
    print("Subject:", d["subject"])
    print(d["body"][:300], "...")

    step("5. Two-question mock interview")
    base = {"resume_text": resume, "jd_text": jd, "role": "Backend Engineer", "missing_skills": m.missing_skills,
            "session_id": sid, "resume_id": rid}
    st = interview.step(base)["interview"]
    for answer in ("idk", "I built a payments ledger in FastAPI and PostgreSQL, used idempotency keys so retries "
                          "never double-posted, tested it with pytest, and saw zero duplicate entries in load tests."):
        print("Q:", st["current_question"]["text"])
        out = interview.step({**base, "interview": st, "answer": answer})
        st = out["interview"]
        print("   score:", out["last_eval"]["scores"]["overall"], "| next is follow-up:", st["current_question"].get("is_followup"))
    step("6. Reminder agent (plans only, nothing is added to a calendar)")
    from datetime import datetime, timedelta
    from careerpilot.tools import calendar_tool
    base = datetime.now(calendar_tool.IST).date()
    text = f"Last date to apply: {(base + timedelta(days=12)).isoformat()}. Interview on {(base + timedelta(days=20)).isoformat()} at 11 am."
    plan = reminders.run_reminder_agent(text, company="Acme", role="SDE-1", use_llm=llm.available())
    for it in plan["plan"]:
        print(f"  {it['date']} {it['time'] or 'all day':8} {it['title']}  reminders(min before)={it['reminders_min']}")

    print("\nSmoke run finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
