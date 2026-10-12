"""Resume QA (RAG) node."""
from __future__ import annotations

from .. import llm, prompts, security, vectorstore


def answer_question(resume_id: int, question: str) -> dict:
    """Return {'answer': str, 'sources': [(section, snippet)]}."""
    question = security.cap_chat(question)
    hits = vectorstore.retrieve(resume_id, question, k=4)
    if not hits:
        return {"answer": prompts.NOT_FOUND, "sources": []}
    context = "\n\n".join(f"[{sec}]\n{txt}" for sec, txt in hits)
    user = f"{security.wrap('context', context)}\n\nQuestion: {question}"
    answer = llm.chat(prompts.QA_SYSTEM, user, tier="fast", temperature=0.0)
    return {"answer": answer, "sources": hits}
