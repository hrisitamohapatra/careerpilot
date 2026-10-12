from careerpilot.nodes import interview as iv


def test_decide_rules():
    assert iv.decide(3, False, 0, 5) == "followup"
    assert iv.decide(3, True, 0, 5) == "next"      # only one follow-up per question
    assert iv.decide(8, False, 0, 5) == "next"
    assert iv.decide(8, False, 4, 5) == "report"
    assert iv.decide(2, True, 4, 5) == "report"


BASE = {"resume_text": "Python developer. Built a payments ledger with FastAPI and PostgreSQL.",
        "jd_text": "Backend role needing Kafka and Docker.", "role": "Backend Engineer",
        "missing_skills": ["kafka", "docker"], "session_id": "s", "resume_id": 1}


def test_bad_answer_triggers_exactly_one_followup_then_good_moves_on():
    s = iv.step(dict(BASE))
    st = s["interview"]
    assert st["status"] == "asking" and len(st["question_plan"]) == 5
    assert st["question_plan"][-1]["type"] == "behavioral"

    s = iv.step({**BASE, "interview": st, "answer": "idk"})
    st = s["interview"]
    assert st["current_question"]["is_followup"] and st["followup_used"] and st["current_index"] == 0

    s = iv.step({**BASE, "interview": st, "answer": "no idea still"})   # weak again: no second follow-up
    st = s["interview"]
    assert st["current_index"] == 1 and not st["current_question"]["is_followup"]

    good = ("In my payments ledger project I used FastAPI and PostgreSQL. I designed idempotency keys so retried "
            "requests never double-posted, wrote integration tests with pytest, and cut duplicate entries to zero "
            "during load testing. The result was a ledger the team trusted for reconciliation. ") * 2
    s = iv.step({**BASE, "interview": st, "answer": good})
    st = s["interview"]
    assert st["current_index"] == 2 and not st["followup_used"]


def test_full_run_saves_report():
    from careerpilot import store  # noqa: F401
    st = iv.step(dict(BASE))["interview"]
    good = "I built and tested a FastAPI ledger with PostgreSQL, handled retries with idempotency keys, and measured zero duplicates. " * 4
    for _ in range(5):
        st = iv.step({**BASE, "interview": st, "answer": good})["interview"]
        if st["status"] == "done":
            break
    assert st["status"] == "done" and 0 <= st["report"]["overall"] <= 10
    assert st["report"]["per_question"] and st["report"]["study_plan"]
