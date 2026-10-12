"""Feed-based remote sources hit the provider at most once per day, whatever the query."""
from careerpilot.tools import http
from careerpilot.tools.job_sources.remote_sources import Remotive


def test_remotive_called_once_for_many_queries(monkeypatch):
    calls = []

    def fake(url, *a, **k):
        calls.append(url)
        return {"jobs": [
            {"title": "Python Developer", "company_name": "A", "candidate_required_location": "Worldwide", "url": "https://remotive.com/1", "description": "Python APIs"},
            {"title": "Sales Lead", "company_name": "B", "candidate_required_location": "USA", "url": "https://remotive.com/2", "description": "Selling"},
        ]}

    monkeypatch.setattr(http, "get_json", fake)
    src = Remotive()
    a = src.search_cached("python developer", "Pune")
    b = src.search_cached("sales", "Pune")
    c = src.search_cached("python backend", "Delhi NCR")
    assert len(calls) == 1
    assert [j.title for j in a] == ["Python Developer"] and [j.title for j in b] == ["Sales Lead"] and len(c) == 1
