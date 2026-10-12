"""RAG plumbing with a tiny offline embedder (the real MiniLM model is used in the app)."""
import hashlib
import math
import re
from pathlib import Path

import pytest

from careerpilot import config, parsing, prompts, vectorstore
from careerpilot.nodes import qa

SAMPLE = (Path(config.DATA_DIR) / "samples" / "resume_backend.txt").read_text(encoding="utf-8")


class HashEmbeddings:
    """Bag-of-words hashing embedder: deterministic, no downloads."""

    dim = 256

    def _vec(self, text):
        v = [0.0] * self.dim
        for w in re.findall(r"[a-z0-9+#.]+", text.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dim] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


@pytest.fixture(autouse=True)
def fake_embeddings(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CHROMA_DIR", tmp_path / "chroma")
    vectorstore._embeddings.cache_clear()
    monkeypatch.setattr(vectorstore, "_embeddings", lambda: HashEmbeddings())


def test_sections_are_detected():
    sections = {c.section for c in parsing.split_sections(SAMPLE)}
    assert {"Skills", "Experience", "Projects", "Education"} <= sections


def test_generic_chunking_when_no_headings():
    chunks = parsing.split_sections("word " * 1200)
    assert len(chunks) > 1 and all(c.section == "General" for c in chunks)


def test_retrieval_returns_section_metadata():
    vectorstore.index_resume(1, parsing.split_sections(SAMPLE))
    hits = vectorstore.retrieve(1, "Which skills do I have? Python FastAPI Docker", k=4, max_distance=2.0)
    assert hits and any(sec == "Skills" for sec, _ in hits)


def test_qa_answers_with_context_and_not_found(monkeypatch):
    vectorstore.index_resume(2, parsing.split_sections(SAMPLE))
    seen = {}

    def fake_chat(system, user, **k):
        seen["user"] = user
        return "Python and FastAPI [Skills]"

    monkeypatch.setattr(qa.llm, "chat", fake_chat)
    real = vectorstore.retrieve  # the toy hashing embedder needs a looser distance cut-off than MiniLM
    monkeypatch.setattr(vectorstore, "retrieve", lambda rid, q, k=4: real(rid, q, k=k, max_distance=2.0))
    res = qa.answer_question(2, "What are my top skills?")
    assert "<context>" in seen["user"] and res["sources"]
    # nothing close enough -> exact not-found reply, model is never called
    monkeypatch.setattr(vectorstore, "retrieve", lambda *a, **k: [])
    assert qa.answer_question(2, "favourite colour?")["answer"] == prompts.NOT_FOUND
