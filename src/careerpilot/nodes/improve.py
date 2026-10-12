"""Improve and Generate: bullet rewrites, cover letter and recruiter email (never invents facts)."""
from __future__ import annotations

from .. import llm, prompts, security
from ..schemas import BulletList, BulletRewrite, DraftOut


def rewrite_bullets(resume_text: str, jd_text: str = "", missing: list[str] | None = None) -> list[BulletRewrite]:
    """Returns [{original, improved, reason, needs_metric}]. Raises LLMUnavailable without a key."""
    user = security.wrap("resume", resume_text[:8000])
    if jd_text.strip():
        user += "\n\n" + security.wrap("job", jd_text[:4000])
    if missing:
        user += f"\n\nSkills the job wants that the resume lacks (do NOT claim them): {', '.join(missing[:8])}"
    out = llm.structured(BulletList, prompts.BULLETS_SYSTEM, user, tier="strong", temperature=0.3)
    return out.items[:6]


def _candidate_name(resume_text: str) -> str:
    for line in resume_text.splitlines():
        line = line.strip()
        if line:
            return line if 1 <= len(line.split()) <= 4 and "@" not in line else "Regards"
    return "Regards"


def _template(resume_text: str, job: dict, matched: list[str], missing: list[str]) -> DraftOut:
    name = _candidate_name(resume_text)
    role, company = job.get("title", "the role"), job.get("company", "your company")
    skills = ", ".join(matched[:5]) if matched else "the skills listed on my resume"
    body = (
        f"Hello,\n\nI am writing to apply for the {role} position at {company}. My resume shows hands-on work "
        f"with {skills}, which lines up with what the role asks for.\n\nI would be glad to talk about how I "
        f"can contribute. My resume is attached to this message on request.\n\nThank you for your time.\n\n{name}"
    )
    letter = body.replace("Hello,", "Dear Hiring Team,")
    return DraftOut(subject=f"Application for {role}", email_body=body, cover_letter=letter)


def write_documents(resume_text: str, job: dict, matched: list[str], missing: list[str]) -> tuple[DraftOut, bool]:
    """Draft a recruiter email and cover letter for one job. Returns (draft, used_ai)."""
    draft: DraftOut | None = None
    used_ai = False
    if llm.available():
        job_text = "{} at {}. {}".format(job.get("title", ""), job.get("company", ""), job.get("description", "")[:4000])
        user = (
            security.wrap("resume", resume_text[:8000]) + "\n\n"
            + security.wrap("job", job_text) + "\n\n"
            + "Matched skills: " + ", ".join(matched[:10]) + "\nMissing skills: " + ", ".join(missing[:8])
        )
        try:
            draft = llm.structured(DraftOut, prompts.DRAFT_SYSTEM, user, tier="strong", temperature=0.6)
            used_ai = True
        except (llm.LLMUnavailable, ValueError):
            draft = None
    if draft is None:
        draft = _template(resume_text, job, matched, missing)
    subject = " ".join(draft.subject.split())[: security.config.MAX_SUBJECT_CHARS]
    draft = DraftOut(
        subject=subject or f"Application for {job.get('title', 'the role')}",
        email_body=draft.email_body.strip()[: security.config.MAX_BODY_CHARS],
        cover_letter=draft.cover_letter.strip()[: security.config.MAX_BODY_CHARS],
    )
    return draft, used_ai
