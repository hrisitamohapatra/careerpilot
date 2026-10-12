import time

import pytest

from careerpilot.schemas import Job
from careerpilot.tools import http
from careerpilot.tools.job_sources import aggregator
from careerpilot.tools.job_sources.adzuna import Adzuna
from careerpilot.tools.job_sources.base import JobSource
from careerpilot.tools.job_sources.jooble import Jooble
from careerpilot.tools.job_sources.remote_sources import Arbeitnow, Jobicy, RemoteOK, Remotive


def test_adzuna_normalises(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    monkeypatch.setattr(http, "get_json", lambda *a, **k: {"results": [{
        "title": "Backend <b>Engineer</b>", "company": {"display_name": "Acme"},
        "location": {"display_name": "Bengaluru, Karnataka"}, "redirect_url": "https://adzuna.in/x",
        "description": "<p>Build &amp; ship APIs</p><script>bad()</script>", "created": "2026-10-01",
        "salary_min": 1200000, "salary_max": 1800000}]})
    jobs = Adzuna().search("backend", "Bengaluru")
    j = jobs[0]
    assert isinstance(j, Job) and j.source == "Adzuna" and j.currency == "INR"
    assert j.title == "Backend Engineer" and "<" not in j.description and "&amp;" not in j.description
    assert j.salary_text() == "INR 12.0L to 18.0L"


def test_jooble_normalises(monkeypatch):
    monkeypatch.setenv("JOOBLE_API_KEY", "secret")
    monkeypatch.setattr(http, "post_json", lambda *a, **k: {"jobs": [{
        "title": "Python Dev", "company": "Beta", "location": "Pune", "link": "https://jooble.org/j/1",
        "snippet": "Work with <i>Python</i>", "salary": "₹6,00,000 - ₹9,00,000 per year", "updated": "2026-10-02"}]})
    j = Jooble().search("python", "Pune")[0]
    assert j.source == "Jooble" and j.salary_min == 600000 and j.salary_max == 900000 and "<" not in j.description


def test_remote_adapters(monkeypatch):
    def fake(url, *a, **k):
        if "remotive" in url:
            return {"jobs": [{"title": "Dev", "company_name": "R", "candidate_required_location": "Worldwide", "url": "https://remotive.com/1", "description": "<b>x</b>"}]}
        if "remoteok" in url:
            return [{"legal": "notice"}, {"position": "Python Dev", "company": "OK", "location": "Anywhere", "url": "https://remoteok.com/1", "tags": ["python"], "description": "d"}]
        if "jobicy" in url:
            return {"jobs": [{"jobTitle": "Dev", "companyName": "J", "jobGeo": "Anywhere", "url": "https://jobicy.com/1", "jobDescription": "d"}]}
        return {"data": [{"title": "Python Dev", "company_name": "A", "location": "Berlin", "url": "https://www.arbeitnow.com/1", "remote": True, "description": "d", "tags": ["python"]}]}

    monkeypatch.setattr(http, "get_json", fake)
    for cls, name in [(Remotive, "Remotive"), (RemoteOK, "RemoteOK"), (Jobicy, "Jobicy"), (Arbeitnow, "Arbeitnow")]:
        jobs = cls().search("python dev", "")
        assert jobs and jobs[0].source == name
    # RemoteOK: first element (legal notice) is skipped
    assert len(RemoteOK().search("python dev", "")) == 1


def test_http_allowlist_blocks_other_hosts():
    with pytest.raises(http.SourceError):
        http.get_json("https://evil.example.com/steal")
    with pytest.raises(http.SourceError):
        http.get_json("http://remotive.com/api")  # not https


class Fake(JobSource):
    def __init__(self, name, jobs=None, exc=None, delay=0, india=True):
        self.name, self._jobs, self._exc, self._delay, self.india_focused = name, jobs or [], exc, delay, india

    def search_cached(self, q, c):
        if self._delay:
            time.sleep(self._delay)
        if self._exc:
            raise self._exc
        return self._jobs


def J(title, company, loc, src):
    return Job(source=src, title=title, company=company, location=loc, url="https://x.com")


def test_aggregator_isolates_failures_and_dedupes():
    reg = {
        "A": Fake("A", [J("Backend Engineer", "Acme", "Pune", "A"), J("Data Analyst", "Z", "Pune", "A")]),
        "B": Fake("B", exc=RuntimeError("boom")),
        "C": Fake("C", delay=2),
        "D": Fake("D", [J("backend engineer", "ACME", "Pune, MH", "D")]),
    }
    out = aggregator.search("backend", "Pune", ["A", "B", "C", "D"], True, timeout=0.5, registry=reg)
    assert out.statuses["C"] == "timed out" and out.statuses["B"].startswith("failed")
    assert out.statuses["A"] == "2 listings"
    assert len(out.jobs) == 2  # duplicate merged
    assert not out.used_sample


def test_remote_sources_filtered_to_india_eligible():
    reg = {"R": Fake("R", [J("Dev", "X", "USA only", "R"), J("Dev2", "Y", "Worldwide", "R")], india=False)}
    out = aggregator.search("dev", "Pune", ["R"], True, registry=reg)
    assert [j.company for j in out.jobs] == ["Y"]
    skipped = aggregator.search("dev", "Pune", ["R"], False, registry=reg)
    assert skipped.statuses["R"].startswith("skipped") and skipped.used_sample


def test_all_sources_down_falls_back_to_sample():
    out = aggregator.search("backend engineer", "Bengaluru", aggregator.DEFAULT_ENABLED, True,
                            registry={n: Fake(n, exc=RuntimeError("x")) for n in aggregator.DEFAULT_ENABLED})
    assert out.used_sample and out.jobs and all(j.source == "Sample data" for j in out.jobs)


def test_no_keys_means_sample_with_notice():
    out = aggregator.search("python developer", "Pune", ["Adzuna", "Jooble"], False)
    assert out.statuses["Adzuna"] == "not configured" and out.used_sample


def test_sample_data_is_large_enough():
    assert len(aggregator.load_sample()) >= 20
