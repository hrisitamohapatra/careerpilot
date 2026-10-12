from __future__ import annotations

import re

from ... import config
from .. import http
from .base import JobSource, make_job


def _salary(text: str):
    """Jooble gives salary as free text like '₹6,00,000 - ₹9,00,000 per year'. Best effort."""
    nums = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", text or "") if len(n.replace(",", "")) >= 4]
    if not nums:
        return None, None
    return min(nums), max(nums)


class Jooble(JobSource):
    name = "Jooble"
    requires_key = True
    india_focused = True
    cache_hours = 6
    env_keys = ("JOOBLE_API_KEY",)
    attribution = "Jobs via Jooble"

    def fetch(self, query, city):
        payload = {"keywords": query, "location": "" if city == "Anywhere in India" else (city or "India")}
        url = "https://jooble.org/api/" + config.env("JOOBLE_API_KEY")  # never logged
        data = http.post_json(url, payload)
        out = []
        for r in (data or {}).get("jobs", []):
            lo, hi = _salary(r.get("salary", ""))
            out.append(make_job(
                self.name, r.get("title"), r.get("company", ""), r.get("location", ""), r.get("link", ""),
                r.get("snippet", ""), r.get("updated", ""), lo, hi, "INR" if lo else "",
            ))
        return out
