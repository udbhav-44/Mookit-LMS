"""A scripted LLMProvider for orchestrator tests.

Each call to ``respond`` pops the next scripted "round" (a list of LLMEvents) so multi-round
plan-execute loops can be exercised deterministically. Records the kwargs of each respond call.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.contracts.types import (
    AssistantDelta,
    LLMEvent,
    LLMProvider,
    ResponseCompleted,
    ToolCallArgsDone,
    ToolCallStarted,
)


def prose_round(text: str, *, response_id: str = "resp") -> list[LLMEvent]:
    return [AssistantDelta(text=text), ResponseCompleted(response_id=response_id)]


def tool_round(
    *, name: str, call_id: str, arguments: dict, response_id: str = "resp"
) -> list[LLMEvent]:
    return [
        ToolCallStarted(call_id=call_id, name=name),
        ToolCallArgsDone(call_id=call_id, name=name, arguments=arguments),
        ResponseCompleted(response_id=response_id),
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
