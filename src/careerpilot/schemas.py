"""All Pydantic models (LLM structured outputs + shared data)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ------------------------------------------------------------------ jobs
class Job(BaseModel):
    source: str
    title: str
    company: str = ""
    location: str = ""
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    currency: str = ""
    url: str = ""
    description: str = ""
    posted_date: str = ""

    def dedupe_key(self) -> tuple[str, str, str]:
        import re

        norm = lambda s: re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()  # noqa: E731
        city = norm(self.location.split(",")[0])
        return (norm(self.company), norm(self.title), city)

    def salary_text(self) -> str:
        if not self.salary_min and not self.salary_max:
            return "Not listed"
        cur = self.currency or "INR"

        def fmt(v: float) -> str:
            if cur == "INR" and v >= 100000:
                return f"{v / 100000:.1f}L"
            return f"{v:,.0f}"

        lo, hi = self.salary_min, self.salary_max
        if lo and hi and lo != hi:
            return f"{cur} {fmt(lo)} to {fmt(hi)}"
        return f"{cur} {fmt(lo or hi)}"


# ------------------------------------------------------------ match / skills
class SkillProfile(BaseModel):
    skills: list[str] = Field(default_factory=list)
    years_experience: float = 0
    education: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class SoftRating(BaseModel):
    score: int = Field(ge=0, le=100)
    reason: str


class SoftScores(BaseModel):
    experience: SoftRating
    education: SoftRating
    projects: SoftRating


class CategoryScore(BaseModel):
    name: str
    score: float
    weight: int
    reason: str = ""


class MatchResult(BaseModel):
    overall_score: float
    breakdown: list[CategoryScore]
    matched_skills: list[str]
    missing_skills: list[str]
    suggestions: list[str] = Field(default_factory=list)
    notes: str = ""


# ------------------------------------------------------------------ router
Intent = Literal["qa", "match", "improve", "jobs", "apply", "interview", "remind", "smalltalk", "clarify"]


class RouterOut(BaseModel):
    intent: Intent


# ------------------------------------------------------------- job agent
class KeywordPlan(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=4)

    @field_validator("queries")
    @classmethod
    def _trim(cls, v: list[str]) -> list[str]:
        out = [q.strip()[:80] for q in v if q and q.strip()]
        if not out:
            raise ValueError("no queries")
        return out


class EvalDecision(BaseModel):
    enough: bool
    reason: str = ""
    new_queries: list[str] = Field(default_factory=list)
    suggest_remote: bool = False


# --------------------------------------------------------- improve / apply
class BulletRewrite(BaseModel):
    original: str
    improved: str
    reason: str
    needs_metric: bool = False


class BulletList(BaseModel):
    items: list[BulletRewrite]


class DraftOut(BaseModel):
    subject: str
    email_body: str
    cover_letter: str


# ------------------------------------------------------------ reminder agent
class ReminderCandidate(BaseModel):
    """What the model reads from text. Code validates every field before anything is planned."""
    kind: Literal["deadline", "interview", "test", "follow_up", "other"] = "other"
    title: str = ""            # the role or what it is, e.g. "SDE-1"
    company: str = ""
    date: str = ""             # ISO yyyy-mm-dd
    time: str = ""             # 24h HH:MM, empty if not stated


class ReminderExtraction(BaseModel):
    items: list[ReminderCandidate] = Field(default_factory=list)


class PlannedReminder(BaseModel):
    kind: Literal["deadline", "interview", "test", "follow_up", "prep", "other"]
    title: str
    company: str = ""
    date: str                  # ISO
    time: str = ""             # HH:MM or "" when all-day
    all_day: bool = False
    duration_min: int = 60
    reminders_min: list[int] = Field(default_factory=list)
    note: str = ""
    key: str = ""              # dedupe key
    add: bool = True


# --------------------------------------------------------------- interview
class InterviewQuestion(BaseModel):
    text: str
    type: Literal["resume", "skill_gap", "behavioral"] = "resume"
    topic: str = ""


class QuestionPlan(BaseModel):
    questions: list[InterviewQuestion] = Field(min_length=1)


class AnswerEvaluation(BaseModel):
    relevance: int = Field(ge=0, le=10)
    depth: int = Field(ge=0, le=10)
    clarity: int = Field(ge=0, le=10)
    examples: int = Field(ge=0, le=10)
    overall: float = Field(ge=0, le=10)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    improved_sample_answer: str = ""
    justification: str = ""


class FollowUp(BaseModel):
    question: str


class ReportExtras(BaseModel):
    top_strengths: list[str] = Field(default_factory=list)
    top_weaknesses: list[str] = Field(default_factory=list)
    study_plan: list[str] = Field(default_factory=list)
