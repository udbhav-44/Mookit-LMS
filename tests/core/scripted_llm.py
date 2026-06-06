"""A scripted LLMProvider for orchestrator tests.

Emits the canonical generic ``LLMEvent(event_type, data)`` stream. Each call to ``respond`` pops the
next scripted "round" so multi-round plan-execute loops can be exercised deterministically.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.contracts.llm import LLMEvent, LLMProvider


def prose_round(text: str, *, response_id: str = "resp") -> list[LLMEvent]:
    return [
        LLMEvent(event_type="assistant_delta", data={"text": text}),
        LLMEvent(event_type="response_completed", data={"response_id": response_id}),
    ]


def tool_round(*, name: str, call_id: str, arguments: dict, response_id: str = "resp") -> list[LLMEvent]:
    return [
        LLMEvent(event_type="tool_call_started", data={"call_id": call_id, "name": name}),
        LLMEvent(
            event_type="tool_call_args_done",
            data={"call_id": call_id, "name": name, "arguments": arguments},
        ),
        LLMEvent(event_type="response_completed", data={"response_id": response_id}),
    ]


class ScriptedLLM(LLMProvider):
    def __init__(self, rounds: list[list[LLMEvent]]) -> None:
        self._rounds = list(rounds)
        self.calls: list[dict[str, Any]] = []

    def respond(self, **kwargs: Any) -> AsyncIterator[LLMEvent]:
        self.calls.append(kwargs)
        events = self._rounds.pop(0) if self._rounds else prose_round("")
        return _aiter(events)

    async def respond_structured(self, **kwargs: Any):  # pragma: no cover - not used here
        raise NotImplementedError


async def _aiter(events: list[LLMEvent]) -> AsyncIterator[LLMEvent]:
    for e in events:
        yield e
