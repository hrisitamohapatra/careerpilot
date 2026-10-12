"""The only place outbound job-API HTTP happens: host allowlist, timeouts, retry with backoff.

URLs are never logged or put in error messages (the Jooble key sits in its URL path).
"""
from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import requests

ALLOWED_HOSTS = {
    "api.adzuna.com", "jooble.org", "remotive.com", "remoteok.com", "jobicy.com", "www.arbeitnow.com",
}
USER_AGENT = "CareerPilot/1.0 (student project)"


class SourceError(RuntimeError):
    """Generic failure with a message that never contains the URL or any key."""


def _check(url: str) -> None:
    p = urlparse(url)
    if p.scheme != "https" or p.hostname not in ALLOWED_HOSTS:
        raise SourceError("Blocked: host is not on the allowlist.")


def _request(method: str, url: str, *, timeout: float, retries: int, **kw: Any) -> Any:
    _check(url)
    headers = {"User-Agent": USER_AGENT, **(kw.pop("headers", None) or {})}
    delay = 1.0
    for attempt in range(retries + 1):
        try:
            r = requests.request(method, url, timeout=timeout, headers=headers, **kw)
        except requests.Timeout:
            raise SourceError("timed out")
        except requests.RequestException:
            if attempt == retries:
                raise SourceError("request failed")
            time.sleep(delay)
            delay *= 2
            continue
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == retries:
                raise SourceError(f"service busy (HTTP {r.status_code})")
            time.sleep(delay)
            delay *= 2
            continue
        if r.status_code >= 400:
            raise SourceError(f"rejected (HTTP {r.status_code})")
        try:
            return r.json()
        except ValueError:
            raise SourceError("unreadable response")
    raise SourceError("request failed")


def get_json(url: str, params: dict | None = None, headers: dict | None = None,
             timeout: float = 10, retries: int = 1) -> Any:
    return _request("GET", url, timeout=timeout, retries=retries, params=params, headers=headers)


def post_json(url: str, payload: dict, timeout: float = 10, retries: int = 1) -> Any:
    return _request("POST", url, timeout=timeout, retries=retries, json=payload)
