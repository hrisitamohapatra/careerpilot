from __future__ import annotations

from ... import config
from .. import http
from .base import JobSource, make_job

BASE = "https://api.adzuna.com/v1/api/jobs/in/search/1"


class Adzuna(JobSource):
    name = "Adzuna"
    requires_key = True
    india_focused = True
    cache_hours = 6
    env_keys = ("ADZUNA_APP_ID", "ADZUNA_APP_KEY")
    attribution = "Jobs by Adzuna"

    def fetch(self, query, city):
        params = {
            "app_id": config.env("ADZUNA_APP_ID"),
            "app_key": config.env("ADZUNA_APP_KEY"),
            "what": query,
            "results_per_page": 20,
            "max_days_old": 30,
            "content-type": "application/json",
        }
        if city and city != "Anywhere in India":
            params["where"] = city
        data = http.get_json(BASE, params=params)
        out = []
        for r in (data or {}).get("results", []):
            out.append(make_job(
                self.name, r.get("title"), (r.get("company") or {}).get("display_name", ""),
                (r.get("location") or {}).get("display_name", ""), r.get("redirect_url", ""),
                r.get("description", ""), r.get("created", ""), r.get("salary_min"), r.get("salary_max"), "INR",
            ))
        return out
