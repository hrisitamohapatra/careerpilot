"""Base class for job sources + helpers shared by adapters."""
from __future__ import annotations

from urllib.parse import urlparse

from ... import config, db, security
from ...schemas import Job


def safe_url(url: str) -> str:
    """Only http(s) links are kept; they are shown to the user, never fetched."""
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return ""
    return url.strip() if p.scheme in ("http", "https") and p.netloc else ""


def to_float(v) -> float | None:
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def make_job(source: str, title: str, company: str = "", location: str = "", url: str = "",
             description: str = "", posted_date: str = "", salary_min=None, salary_max=None,
             currency: str = "") -> Job | None:
    """Normalise one raw listing. HTML is stripped; unusable rows return None."""
    title = security.strip_html(str(title or ""), 200)
    if not title:
        return None
    return Job(
        source=source,
        title=title,
        company=security.strip_html(str(company or ""), 120),
        location=security.strip_html(str(location or ""), 120),
        salary_min=to_float(salary_min),
        salary_max=to_float(salary_max),
        currency=(currency or "").upper()[:5],
        url=safe_url(str(url or "")),
        description=security.strip_html(str(description or ""), 6000),
        posted_date=str(posted_date or "")[:32],
    )


def filter_jobs(jobs: list[Job], query: str) -> list[Job]:
    """Keep listings whose title/tags/description mention any meaningful query word."""
    words = {w for w in query.lower().replace("/", " ").split() if len(w) > 2}
    if not words:
        return list(jobs)
    out = []
    for j in jobs:
        blob = f"{j.title} {j.description[:400]}".lower()
        if any(w in blob for w in words):
            out.append(j)
    return out


class JobSource:
    """One free job API. Subclasses implement fetch(); the aggregator calls search_cached()."""

    name = ""
    requires_key = False
    india_focused = False
    feed_based = False          # True: fetch the whole feed once a day and filter locally
    cache_hours = 24
    env_keys: tuple[str, ...] = ()
    attribution = ""

    def configured(self) -> bool:
        return all(config.has(k) for k in self.env_keys)

    def fetch(self, query: str, city: str) -> list[Job]:  # pragma: no cover - network
        raise NotImplementedError

    def search(self, query: str, city: str) -> list[Job]:
        return [j for j in self.fetch(query, city) if j]

    def search_cached(self, query: str, city: str) -> list[Job]:
        if self.feed_based:
            # one fetch per day for the whole feed, then filter locally (respects tight provider limits)
            key = f"jobs|{self.name}|__feed__|"
            hit = db.cache_get(key, self.cache_hours * 3600)
            if hit is None:
                feed = self.search("", city)
                db.cache_set(key, [j.model_dump() for j in feed])
            else:
                feed = [Job(**j) for j in hit]
            return filter_jobs(feed, query)[:20]
        key = f"jobs|{self.name}|{query.strip().lower()}|{city.strip().lower()}"
        hit = db.cache_get(key, self.cache_hours * 3600)
        if hit is not None:
            return [Job(**j) for j in hit]
        jobs = self.search(query, city)
        db.cache_set(key, [j.model_dump() for j in jobs])
        return jobs
