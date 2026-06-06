"""B0.2 live acceptance (CP1) — one real streamed prose turn through OpenAIProvider.

Skipped unless OPENAI_API_KEY is set. Kept tiny (a few tokens) to bound cost.
"""

from __future__ import annotations

import os

import pytest

from app.config import get_settings
from app.contracts.types import AssistantDelta, ResponseCompleted
from app.core.prompts import SYSTEM_PROMPT, build_input
from app.llm.openai_provider import OpenAIProvider

pytestmark = pytest.mark.live


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="no OPENAI_API_KEY")
async def test_live_prose_stream() -> None:
    from openai import AsyncOpenAI

    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    provider = OpenAIProvider(client, default_model=settings.fast_model)

    text_parts: list[str] = []
    completed = False
    events = provider.respond(
        instructions=SYSTEM_PROMPT,
        input=build_input(manifest=None, transcript=[], user_turn="Reply with exactly: pong"),
        temperature=0.0,
    )
    async for ev in events:
        if isinstance(ev, AssistantDelta):
            text_parts.append(ev.text)
        elif isinstance(ev, ResponseCompleted):
            completed = True
    assert completed
    assert "pong" in "".join(text_parts).lower()
