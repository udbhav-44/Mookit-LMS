"""B0.2 live acceptance (CP1) — one real streamed prose turn through OpenAIProvider.

Skipped unless OPENAI_API_KEY is set. Kept tiny (a few tokens) to bound cost.
"""

from __future__ import annotations

import os

import pytest

from app.config import get_settings
from app.core.prompts import SYSTEM_PROMPT, build_input
from app.llm.openai import OpenAIProvider
from app.obs.openai_client import make_async_openai_client

pytestmark = pytest.mark.live


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="no OPENAI_API_KEY")
async def test_live_prose_stream() -> None:
    settings = get_settings()
    client = make_async_openai_client(api_key=settings.openai.api_key.get_secret_value())
    provider = OpenAIProvider(client, default_model=settings.openai.fast_model)

    text_parts: list[str] = []
    completed = False
    events = provider.respond(
        instructions=SYSTEM_PROMPT,
        input=build_input(manifest=None, transcript=[], user_turn="Reply with exactly: pong"),
        tools=[],
        temperature=0.0,
    )
    async for ev in events:
        if ev.event_type == "assistant_delta":
            text_parts.append(ev.data["text"])
        elif ev.event_type == "response_completed":
            completed = True
    assert completed
    assert "pong" in "".join(text_parts).lower()
