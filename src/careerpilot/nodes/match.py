"""JD Match and Score: skills overlap in code, softer categories rated by the strong model."""
from __future__ import annotations

import hashlib
import re

from .. import config, db, llm, prompts, security, skills
from ..schemas import CategoryScore, MatchResult, SkillProfile, SoftRating, SoftScores


def _sha(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8", "ignore")).hexdigest()[:32]


def weighted_total(breakdown: list[CategoryScore]) -> float:
    """Weighted average of category scores (weights sum to 100)."""
    total_w = sum(c.weight for c in breakdown) or 1
    return round(sum(c.score * c.weight for c in breakdown) / total_w, 1)


# ------------------------------------------------------------- extraction
_DEGREE = re.compile(r"(b\.?\s?tech|b\.?\s?e\b|bachelor[^\n,.]*|m\.?\s?tech|master[^\n,.]*|mba|b\.?\s?sc|m\.?\s?sc|phd)", re.I)


def _guess_years(text: str) -> float:
    m = re.search(r"(\d+)\s*(?:\+|-\s*\d+)?\s*years?", text, re.I)
    return float(m.group(1)) if m else 0.0


def _heuristic_profile(text: str) -> SkillProfile:
    sk = sorted(skills.scan_vocab(text))
    edu = sorted({m.group(0).strip() for m in _DEGREE.finditer(text)})[:4]
    return SkillProfile(skills=sk, years_experience=_guess_years(text), education=edu, keywords=sk[:15])


def extract_profile(text: str, kind: str, use_llm: bool = True) -> SkillProfile:
    """Skills and facts from a resume or JD. Cached; LLM output is merged with a code vocabulary scan."""
    key = f"profile:{kind}:{_sha(text)}:{int(use_llm and llm.available())}"
    cached = db.cache_get(key, 7 * 86400)
    if cached:
        return SkillProfile(**cached)
    base = _heuristic_profile(text)
    prof = base
    if use_llm and llm.available():
        try:
            got = llm.structured(
                SkillProfile, prompts.EXTRACT_SYSTEM, security.wrap("doc", text[:9000]), tier="fast"
            )
            merged = sorted({skills.normalize(s) for s in got.skills if s.strip()} | set(base.skills))
            prof = SkillProfile(
                skills=merged[:60],
                years_experience=got.years_experience or base.years_experience,
                education=got.education or base.education,
                certifications=got.certifications,
                keywords=got.keywords[:15] or base.keywords,
            )
        except (llm.LLMUnavailable, ValueError):
            prof = base
    db.cache_set(key, prof.model_dump())
    return prof


# --------------------------------------------------------- softer categories
def _heuristic_soft(resume_text: str, jd_text: str, rp: SkillProfile, jp: SkillProfile, n_matched: int) -> SoftScores:
    has_work = bool(re.search(r"intern|experience|worked|built|developed", resume_text, re.I))
    exp = 55 if has_work else 25
    if jp.years_experience and jp.years_experience > 3:
        exp -= 15
    edu_ok = bool(_DEGREE.search(resume_text))
    edu = 75 if edu_ok else 40
    proj = min(90, 40 + 8 * n_matched) if re.search(r"project", resume_text, re.I) else 30
    return SoftScores(
        experience=SoftRating(score=max(0, exp), reason="Estimated from the resume text (AI rating unavailable)."),
        education=SoftRating(score=edu, reason="Estimated from degree mentions (AI rating unavailable)."),
        projects=SoftRating(score=proj, reason="Estimated from project mentions and matched skills (AI rating unavailable)."),
    )


def _soft_scores(resume_text: str, jd_text: str, rp: SkillProfile, jp: SkillProfile, n_matched: int,
                 use_llm: bool) -> tuple[SoftScores, bool]:
    if use_llm and llm.available():
        user = (
            f"{security.wrap('resume', resume_text[:7000])}\n\n{security.wrap('job', jd_text[:5000])}\n\n"
            f"Resume years of experience: {rp.years_experience}. Job asks for: {jp.years_experience} years."
        )
        try:
            return llm.structured(SoftScores, prompts.SOFT_SYSTEM, user, tier="strong", temperature=0.0), True
        except (llm.LLMUnavailable, ValueError):
            pass
    return _heuristic_soft(resume_text, jd_text, rp, jp, n_matched), False


# -------------------------------------------------------------- main entry
def compute_match(resume_text: str, jd_text: str, use_llm: bool = True) -> MatchResult:
    """Explainable weighted score. Temperature 0, cached by hash of resume + JD."""
    resume_text = security.clean_text(resume_text)
    jd_text = security.strip_html(jd_text, limit=8000) if "<" in jd_text else security.clean_text(jd_text, 8000)
    key = f"match:{_sha(resume_text, jd_text)}:{int(use_llm and llm.available())}"
    cached = db.cache_get(key, 30 * 86400)
    if cached:
        return MatchResult(**cached)

    rp = extract_profile(resume_text, "resume", use_llm)
    jp = extract_profile(jd_text, "jd", use_llm)
    matched, missing = skills.overlap(rp.skills, jp.skills)

    n_jd = len(matched) + len(missing)
    skill_score = round(100 * len(matched) / n_jd, 1) if n_jd else 50.0
    skill_reason = (
        f"{len(matched)} of {n_jd} skills the job asks for appear in your resume."
        if n_jd else "No clear skills were found in the job description."
    )

    kw = {skills.normalize(k) for k in (jp.keywords + jp.skills) if k.strip()}
    low = resume_text.lower()
    hits = [k for k in kw if k and k in low]
    ats_score = round(100 * len(hits) / len(kw), 1) if kw else skill_score
    ats_reason = f"{len(hits)} of {len(kw)} job keywords appear in your resume text."

    soft, used_llm = _soft_scores(resume_text, jd_text, rp, jp, len(matched), use_llm)
    w = config.MATCH_WEIGHTS
    breakdown = [
        CategoryScore(name="Skills", score=skill_score, weight=w["skills"], reason=skill_reason),
        CategoryScore(name="Experience", score=soft.experience.score, weight=w["experience"], reason=soft.experience.reason),
        CategoryScore(name="Education and certifications", score=soft.education.score, weight=w["education"], reason=soft.education.reason),
        CategoryScore(name="ATS keywords", score=ats_score, weight=w["ats_keywords"], reason=ats_reason),
        CategoryScore(name="Projects and achievements", score=soft.projects.score, weight=w["projects"], reason=soft.projects.reason),
    ]
    suggestions = [
        f"If you have real experience with {m}, add it to your skills and a project bullet." for m in missing[:3]
    ]
    if ats_score < 50:
        suggestions.append("Mirror the job's wording in your bullets so keyword filters pick them up.")
    result = MatchResult(
        overall_score=weighted_total(breakdown),
        breakdown=breakdown,
        matched_skills=matched,
        missing_skills=missing,
        suggestions=suggestions,
        notes="" if used_llm else "Softer categories were estimated in code because the AI model was not available.",
    )
    db.cache_set(key, result.model_dump())
    return result
