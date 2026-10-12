"""Remote-job adapters: Remotive, RemoteOK, Jobicy, Arbeitnow (all keyless).

Remotive allows only ~4 requests a day (and 2 per minute), so Remotive, RemoteOK and Arbeitnow are
feed-based: the whole feed is fetched at most once every 24 hours and filtered locally.
"""
from __future__ import annotations

from .. import http
from .base import JobSource, make_job


class Remotive(JobSource):
    name = "Remotive"
    feed_based = True
    cache_hours = 24
    attribution = "Remote jobs from Remotive (remotive.com), linked to the original listing"

    def fetch(self, query, city):
        data = http.get_json("https://remotive.com/api/remote-jobs", params={"limit": 150})
        return [
            make_job(self.name, r.get("title"), r.get("company_name", ""), r.get("candidate_required_location", ""),
                     r.get("url", ""), r.get("description", ""), r.get("publication_date", ""))
            for r in (data or {}).get("jobs", [])
        ]


class RemoteOK(JobSource):
    name = "RemoteOK"
    feed_based = True
    cache_hours = 24
    attribution = "Remote jobs from Remote OK (remoteok.com). Each listing links back to Remote OK"

    def fetch(self, query, city):
        data = http.get_json("https://remoteok.com/api")
        rows = data[1:] if isinstance(data, list) else []  # first element is a legal notice
        out = []
        for r in rows[:150]:
            tags = " ".join(r.get("tags") or [])
            out.append(make_job(
                self.name, r.get("position"), r.get("company", ""), r.get("location") or "Worldwide",
                r.get("url", ""), f"{tags}. {r.get('description', '')}", r.get("date", ""),
                r.get("salary_min"), r.get("salary_max"), "USD" if r.get("salary_min") else "",
            ))
        return out


class Jobicy(JobSource):
    name = "Jobicy"
    cache_hours = 24
    attribution = "Remote jobs from Jobicy (jobicy.com)"

    def fetch(self, query, city):
        data = http.get_json("https://jobicy.com/api/v2/remote-jobs", params={"count": 20, "tag": query})
        return [
            make_job(self.name, r.get("jobTitle"), r.get("companyName", ""), r.get("jobGeo", ""),
                     r.get("url", ""), r.get("jobDescription", ""), r.get("pubDate", ""),
                     r.get("salaryMin"), r.get("salaryMax"), r.get("salaryCurrency", ""))
            for r in (data or {}).get("jobs", [])
        ]


class Arbeitnow(JobSource):
    name = "Arbeitnow"
    feed_based = True
    cache_hours = 24
    attribution = "Jobs from Arbeitnow (arbeitnow.com)"

    def fetch(self, query, city):
        data = http.get_json("https://www.arbeitnow.com/api/job-board-api")
        out = []
        for r in (data or {}).get("data", []):
            if not r.get("remote"):
                continue
            tags = " ".join(r.get("tags") or [])
            out.append(make_job(self.name, r.get("title"), r.get("company_name", ""), r.get("location") or "Remote",
                                r.get("url", ""), f"{tags}. {r.get('description', '')}", str(r.get("created_at", ""))))
        return out[:150]
