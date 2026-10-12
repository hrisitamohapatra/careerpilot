"""Central LLM access: fast/strong Groq models, retry with backoff, validated structured output."""
from __future__ import annotations

import time
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError as PydanticError

from . import config

T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(RuntimeError):
    """Friendly error shown in the UI (missing key, rate limit...)."""


def available() -> bool:
    """True when a Groq key is configured."""
    return config.has("GROQ_API_KEY")


def _model(name: str, temperature: float):
    if not config.has("GROQ_API_KEY"):
        raise LLMUnavailable("GROQ_API_KEY is not set. Add it to your .env file.")
    from langchain_groq import ChatGroq

    return ChatGroq(
        model=name,
        temperature=temperature,
        max_tokens=config.MAX_OUTPUT_TOKENS,
        timeout=60,
        api_key=config.env("GROQ_API_KEY"),
    )


def get_llm(tier: str = "fast", temperature: float = 0.0):
    return _model(config.MODEL_FAST if tier == "fast" else config.MODEL_STRONG, temperature)


def _retry(fn, attempts: int = 4):
    delay = 2.0
    for i in range(attempts):
        try:
            return fn()
        except LLMUnavailable:
            raise
        except Exception as e:  # noqa: BLE001
            msg = str(e).lower()
            transient = any(k in msg for k in ("429", "rate", "timeout", "503", "502", "500", "overloaded"))
            if not transient or i == attempts - 1:
                if transient:
                    raise LLMUnavailable("The AI service is rate-limited right now. Wait a minute and try again.")
                raise LLMUnavailable("The AI service returned an error. Please try again.")
            time.sleep(delay)
            delay *= 2


def chat(system: str, user: str, tier: str = "fast", temperature: float = 0.0) -> str:
    """Plain text completion."""
    llm = get_llm(tier, temperature)
    msgs = [("system", system), ("human", user)]
    return str(_retry(lambda: llm.invoke(msgs)).content).strip()


def structured(schema: Type[T], system: str, user: str, tier: str = "fast", temperature: float = 0.0) -> T:
    """Structured output validated by Pydantic; one retry feeding the error back."""
    llm = get_llm(tier, temperature).with_structured_output(schema)
    msgs = [("system", system), ("human", user)]
    try:
        return schema.model_validate(_retry(lambda: llm.invoke(msgs)))
    except PydanticError as e:
        msgs.append(("human", f"Your last output failed validation: {str(e)[:500]}. Return valid output."))
        return schema.model_validate(_retry(lambda: llm.invoke(msgs)))
