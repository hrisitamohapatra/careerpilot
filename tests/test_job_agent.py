"""The job agent loop on sample data (no keys needed)."""
from careerpilot.nodes import jobs
from careerpilot.schemas import Job
from careerpilot.tools.job_sources import aggregator

RESUME = "Riya\nSkills\nPython, FastAPI, PostgreSQL, Docker\nExperience\nIntern building REST APIs in Python."


def run(role, city="Bengaluru", remote=False):
    return jobs.run_job_agent({
        "resume_text": RESUME, "target_role": role, "city": city, "include_remote": remote,
        "enabled_sources": ["Adzuna", "Jooble"], "session_id": "s",
    })


def test_relevance_is_not_fooled_by_generic_words():
    ml = Job(source="x", title="Machine Learning Engineer", description="Train models with PyTorch.")
    be = Job(source="x", title="Backend Engineer (SDE-1)", description="Build APIs.")
    assert not jobs.is_relevant(ml, "Backend Engineer") and jobs.is_relevant(be, "Backend Engineer")
    assert jobs.is_relevant(ml, "Software Engineer")  # generic-only role keeps generic matching


def test_good_query_finishes_in_one_round_and_ranks():
    out = run("Backend Engineer")
    assert sum(1 for r in out["rounds"] if r.startswith("Round")) == 1
    assert out["used_sample"] and out["ranked"]
    scores = [r["score"] for r in out["ranked"]]
    assert scores == sorted(scores, reverse=True) and len(scores) <= jobs.TOP_N


def test_vague_query_triggers_refinement_capped_at_two_loops():
    out = run("Quantum Chef")  # nothing relevant anywhere
    rounds = [r for r in out["rounds"] if r.startswith("Round")]
    assert 2 <= len(rounds) <= 3  # first search + at most 2 refinements
    assert any(r.startswith("Not enough") for r in out["rounds"])
    assert out["ranked"]  # still falls back to sample listings instead of an empty screen


def test_no_live_result_wording():
    out = run("Backend Engineer")
    assert "sample listings" in out["rounds"][0]
    assert aggregator.SAMPLE_NAME in out["statuses"]
