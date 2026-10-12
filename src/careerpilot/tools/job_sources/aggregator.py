"""Runs enabled job sources concurrently, isolates failures, merges, de-duplicates, caps."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field

from ... import config
from ...schemas import Job
from .adzuna import Adzuna
from .base import JobSource
from .jooble import Jooble
from .remote_sources import Arbeitnow, Jobicy, RemoteOK, Remotive

SOURCES: dict[str, JobSource] = {s.name: s for s in (Adzuna(), Jooble(), Remotive(), RemoteOK(), Jobicy(), Arbeitnow())}
DEFAULT_ENABLED = ["Adzuna", "Jooble", "Remotive", "RemoteOK"]
SAMPLE_NAME = "Sample data"
PER_SOURCE_TIMEOUT = 12
TOTAL_CAP = 60

INDIA_OK = ("india", "worldwide", "anywhere", "apac", "asia", "remote")


@dataclass
class Outcome:
    jobs: list[Job] = field(default_factory=list)
    statuses: dict[str, str] = field(default_factory=dict)
    used_sample: bool = False


def source_state(name: str) -> str:
    """For the sidebar: 'ready' or 'key not set'."""
    s = SOURCES[name]
    return "ready" if (not s.requires_key or s.configured()) else "key not set"


def india_eligible(job: Job) -> bool:
    loc = (job.location or "").lower()
    return any(k in loc for k in INDIA_OK) if loc else False


def dedupe(jobs: list[Job]) -> list[Job]:
    seen, out = set(), []
    for j in jobs:
        k = j.dedupe_key()
        if k in seen:
            continue
        seen.add(k)
        out.append(j)
    return out


def load_sample() -> list[Job]:
    path = config.DATA_DIR / "sample_jobs.json"
    with open(path, encoding="utf-8") as f:
        return [Job(**r) for r in json.load(f)]


def search_sample(query: str, city: str) -> list[Job]:
    """Keyword + city filter over the bundled fake listings (used when no live source works)."""
    words = {w for w in query.lower().replace("/", " ").split() if len(w) > 2}
    out = []
    for j in load_sample():
        blob = f"{j.title} {j.description}".lower()
        if words and not any(w in blob for w in words):
            continue
        out.append(j)
    if city and city != "Anywhere in India":
        c = city.lower()
        # local and remote listings first, everything else after (never drop results on city alone)
        out.sort(key=lambda j: 0 if c in j.location.lower() else 1 if "remote" in j.location.lower() else 2)
    return out


def _run_one(src: JobSource, query: str, city: str) -> list[Job]:
    return src.search_cached(query, city)


def search(query: str, city: str, enabled: list[str], include_remote: bool,
           timeout: float = PER_SOURCE_TIMEOUT, total_cap: int = TOTAL_CAP,
           registry: dict[str, JobSource] | None = None) -> Outcome:
    """Query every usable enabled source at once. One failing source never breaks the search."""
    reg = registry or SOURCES
    out = Outcome()
    active: list[JobSource] = []
    for name in enabled:
        src = reg.get(name)
        if not src:
            continue
        if src.requires_key and not src.configured():
            out.statuses[name] = "not configured"
        elif not src.india_focused and not include_remote:
            out.statuses[name] = "skipped (remote roles off)"
        else:
            active.append(src)

    collected: list[Job] = []
    if active:
        pool = ThreadPoolExecutor(max_workers=len(active))
        futures = {s.name: pool.submit(_run_one, s, query, city) for s in active}
        for name, fut in futures.items():
            try:
                jobs = fut.result(timeout=timeout)
            except FutureTimeout:
                out.statuses[name] = "timed out"
                continue
            except Exception as e:  # noqa: BLE001 - isolate every failure; message has no URL or key
                out.statuses[name] = f"failed ({str(e)[:40]})"
                continue
            if not reg[name].india_focused:
                jobs = [j for j in jobs if india_eligible(j)]
            out.statuses[name] = f"{len(jobs)} listings"
            collected.extend(jobs)
        pool.shutdown(wait=False, cancel_futures=True)

    if active and collected:
        out.jobs = dedupe(collected)[:total_cap]
    else:
        out.jobs = search_sample(query, city)[:total_cap]
        out.used_sample = True
        out.statuses[SAMPLE_NAME] = f"{len(out.jobs)} listings"
    return out
