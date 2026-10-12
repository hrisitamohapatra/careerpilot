import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from careerpilot import config, db  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Fresh database per test; no real API keys leak in."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    for k in ("GROQ_API_KEY", "ADZUNA_APP_ID", "ADZUNA_APP_KEY", "JOOBLE_API_KEY", "SMTP_USER", "SMTP_APP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    db.init_db()
    yield
