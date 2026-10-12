from pathlib import Path

from careerpilot import config, skills
from careerpilot.nodes import match
from careerpilot.schemas import CategoryScore

SAMPLES = Path(config.DATA_DIR) / "samples"


def test_synonyms_normalise():
    assert skills.normalize("JS") == "javascript"
    assert skills.normalize(" ML ") == "machine learning"
    assert skills.normalize("Postgres") == "postgresql"


def test_overlap_uses_synonyms():
    matched, missing = skills.overlap(["JS", "Postgres", "Docker"], ["javascript", "PostgreSQL", "Kafka"])
    assert matched == ["javascript", "postgresql"]
    assert missing == ["kafka"]


def test_weighted_total():
    b = [CategoryScore(name="a", score=100, weight=40), CategoryScore(name="b", score=0, weight=60)]
    assert match.weighted_total(b) == 40.0


def test_weights_sum_to_100():
    assert sum(config.MATCH_WEIGHTS.values()) == 100


def test_score_is_repeatable_and_explained():
    resume = (SAMPLES / "resume_backend.txt").read_text(encoding="utf-8")
    jd = (SAMPLES / "jd_backend.txt").read_text(encoding="utf-8")
    a = match.compute_match(resume, jd, use_llm=False)
    b = match.compute_match(resume, jd, use_llm=False)
    assert a.overall_score == b.overall_score
    assert len(a.breakdown) == 5
    assert "kafka" in a.missing_skills
    assert "python" in a.matched_skills


def test_better_fit_scores_higher():
    backend = (SAMPLES / "resume_backend.txt").read_text(encoding="utf-8")
    data = (SAMPLES / "resume_data.txt").read_text(encoding="utf-8")
    jd = (SAMPLES / "jd_backend.txt").read_text(encoding="utf-8")
    assert match.compute_match(backend, jd, use_llm=False).overall_score > match.compute_match(data, jd, use_llm=False).overall_score
