"""Central configuration. Secrets come from environment / .env only."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
DB_PATH = Path(os.getenv("CAREERPILOT_DB", ROOT / "careerpilot.db"))
CHROMA_DIR = Path(os.getenv("CAREERPILOT_CHROMA", ROOT / "chroma"))

# --- Models (IDs change often: check the Groq console and override in .env) ---
MODEL_FAST = os.getenv("GROQ_MODEL_FAST", "llama-3.1-8b-instant")
MODEL_STRONG = os.getenv("GROQ_MODEL_STRONG", "llama-3.3-70b-versatile")
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
MAX_OUTPUT_TOKENS = 1500

# --- Upload limits ---
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PDF_PAGES = 10
MAX_TEXT_CHARS = 30_000
ALLOWED_EXTENSIONS = {".pdf", ".docx"}

# --- Chat / agent limits ---
MAX_CHAT_CHARS = 2000
MAX_JOB_REFINE_LOOPS = 2
MAX_FOLLOWUPS_PER_QUESTION = 1
INTERVIEW_QUESTIONS = 5

# --- Match weights (sum = 100) ---
MATCH_WEIGHTS = {
    "skills": 40,
    "experience": 25,
    "education": 15,
    "ats_keywords": 10,
    "projects": 10,
}

# --- Email / calendar ---
MAX_SENDS_PER_SESSION = 5
MAX_SUBJECT_CHARS = 150
MAX_BODY_CHARS = 5000
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"


def env(name: str) -> str:
    """Return an env var (empty string if unset). Never log the value."""
    return os.getenv(name, "").strip()


def has(name: str) -> bool:
    return bool(env(name))
