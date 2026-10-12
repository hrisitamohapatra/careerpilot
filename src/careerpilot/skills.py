"""Skill normalisation, synonyms, vocabulary scan and overlap (all in code, deterministic)."""
from __future__ import annotations

import re

SYNONYMS = {
    "js": "javascript", "ts": "typescript", "ml": "machine learning", "dl": "deep learning",
    "nlp": "natural language processing", "k8s": "kubernetes", "postgres": "postgresql",
    "node": "node.js", "nodejs": "node.js", "node js": "node.js", "reactjs": "react", "react.js": "react",
    "gcp": "google cloud", "amazon web services": "aws", "rest": "rest api", "rest apis": "rest api",
    "restful": "rest api", "restful apis": "rest api", "restful api": "rest api", "cicd": "ci/cd",
    "ci cd": "ci/cd", "scikit learn": "scikit-learn", "sklearn": "scikit-learn", "genai": "generative ai",
    "gen ai": "generative ai", "llms": "llm", "large language models": "llm",
    "large language model": "llm", "powerbi": "power bi", "mongo": "mongodb", "dsa": "data structures and algorithms",
    "data structures": "data structures and algorithms", "oop": "object-oriented programming",
    "oops": "object-oriented programming", "golang": "go", "py": "python", "nextjs": "next.js",
    "next js": "next.js", "tailwindcss": "tailwind", "ms excel": "excel", "microsoft excel": "excel",
    "a/b tests": "a/b testing", "ab testing": "a/b testing", "springboot": "spring boot", "spring": "spring boot",
    "retrieval augmented generation": "rag", "vector database": "vector db", "vector databases": "vector db",
}

VOCAB = [
    "python", "java", "javascript", "typescript", "sql", "postgresql", "mysql", "mongodb", "redis", "kafka",
    "docker", "kubernetes", "aws", "azure", "google cloud", "git", "ci/cd", "fastapi", "flask", "django",
    "spring boot", "react", "node.js", "rest api", "graphql", "machine learning", "deep learning",
    "natural language processing", "pytorch", "tensorflow", "scikit-learn", "pandas", "numpy", "tableau",
    "power bi", "excel", "statistics", "langchain", "langgraph", "rag", "llm", "generative ai", "c++", "go",
    "rust", "linux", "microservices", "system design", "data structures and algorithms", "snowflake",
    "bigquery", "spark", "airflow", "etl", "a/b testing", "pytest", "junit", "jenkins", "terraform", "html",
    "css", "next.js", "tailwind", "solidity", "ethereum", "hardhat", "chromadb", "streamlit", "selenium",
    "rabbitmq", "elasticsearch", "object-oriented programming", "prophet", "vector db", "kotlin", "swift",
    "android", "flutter", "php", "c#", ".net", "sap", "jira", "figma", "agile", "scrum", "devops",
]


def normalize(skill: str) -> str:
    s = (skill or "").lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = s.strip(" .,;:()[]{}\"'")
    return SYNONYMS.get(s, s)


def _pattern(term: str) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9+#.])" + re.escape(term) + r"(?![a-z0-9+#])", re.I)


_PATTERNS = {t: _pattern(t) for t in set(VOCAB) | set(SYNONYMS)}


def scan_vocab(text: str) -> set[str]:
    """Find known skills in free text (normalised)."""
    found = set()
    for term, pat in _PATTERNS.items():
        if len(term) <= 2 and term not in {"go", "py", "js", "ts", "ml", "dl"}:
            continue
        if term in {"go", "py", "rest", "spring", "node", "js", "ts", "ml", "dl", "sap"}:
            # short / ambiguous words: require case-sensitive-ish exact uppercase or known context
            if term == "go" and not re.search(r"\bGo(lang)?\b", text):
                continue
            if term in {"js", "ts", "ml", "dl", "sap"} and not re.search(rf"\b{term.upper()}\b", text):
                continue
            if term in {"py", "rest", "spring", "node"} and not pat.search(text):
                continue
        if pat.search(text):
            found.add(normalize(term))
    return found


def overlap(resume_skills: list[str], jd_skills: list[str]) -> tuple[list[str], list[str]]:
    """Return (matched, missing) using normalised comparison; keeps JD wording for display."""
    have = {normalize(s) for s in resume_skills}
    matched, missing, seen = [], [], set()
    for s in jd_skills:
        n = normalize(s)
        if not n or n in seen:
            continue
        seen.add(n)
        (matched if n in have else missing).append(n)
    return matched, missing
