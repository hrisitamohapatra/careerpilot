"""Chroma vector store with section metadata (local embeddings)."""
from __future__ import annotations

import shutil
from functools import lru_cache

from . import config
from .parsing import Chunk


@lru_cache(maxsize=1)
def _embeddings():
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(model_name=config.EMBEDDING_MODEL)


def _store(resume_id: int):
    from langchain_chroma import Chroma

    return Chroma(
        collection_name=f"resume_{resume_id}",
        embedding_function=_embeddings(),
        persist_directory=str(config.CHROMA_DIR),
    )


def index_resume(resume_id: int, chunks: list[Chunk]) -> None:
    store = _store(resume_id)
    store.add_texts(
        texts=[c.text for c in chunks],
        metadatas=[{"section": c.section, "resume_id": resume_id} for c in chunks],
    )


def retrieve(resume_id: int, question: str, k: int = 4, max_distance: float = 1.6) -> list[tuple[str, str]]:
    """Return [(section, text)] for the top-k chunks; empty if nothing is close."""
    store = _store(resume_id)
    hits = store.similarity_search_with_score(question, k=k)
    return [(d.metadata.get("section", "General"), d.page_content) for d, s in hits if s <= max_distance]


def delete_resume_vectors(resume_id: int) -> None:
    try:
        _store(resume_id).delete_collection()
    except Exception:  # noqa: BLE001
        pass


def wipe_all() -> None:
    shutil.rmtree(config.CHROMA_DIR, ignore_errors=True)
