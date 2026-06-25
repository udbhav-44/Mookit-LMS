"""OpenAI client factory with Langfuse integration-first behavior."""

from __future__ import annotations

from typing import Any


def make_async_openai_client(*, api_key: str) -> Any:
    """Create an AsyncOpenAI-compatible client.

    Prefer Langfuse's OpenAI drop-in integration so prompts/responses, usage,
    and errors are captured automatically.
    """
    try:
        from langfuse.openai import AsyncOpenAI as LangfuseAsyncOpenAI

        return LangfuseAsyncOpenAI(api_key=api_key)
    except Exception:
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=api_key)
