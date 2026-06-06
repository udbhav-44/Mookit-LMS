"""Synthetic OpenAI Responses SDK objects + a fake async client for provider tests.

These mimic the *shape* the SDK exposes (attribute access, ``.type``, async-iterable stream) so we
can assert the StreamTranslator output without any network or real SDK dependency.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any


def ev(type_: str, **kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(type=type_, **kwargs)


def text_delta(text: str) -> SimpleNamespace:
    return ev("response.output_text.delta", delta=text)


def function_call_item(*, item_id: str, call_id: str, name: str) -> SimpleNamespace:
    item = SimpleNamespace(type="function_call", id=item_id, call_id=call_id, name=name)
    return ev("response.output_item.added", item=item)


def args_delta(*, item_id: str, delta: str) -> SimpleNamespace:
    return ev("response.function_call_arguments.delta", item_id=item_id, delta=delta)


def args_done(*, item_id: str, arguments: str) -> SimpleNamespace:
    return ev("response.function_call_arguments.done", item_id=item_id, arguments=arguments)


def completed(*, response_id: str, usage: dict | None = None) -> SimpleNamespace:
    response = SimpleNamespace(id=response_id, usage=usage)
    return ev("response.completed", response=response)


class _Stream:
    def __init__(self, events: list[Any]) -> None:
        self._events = events

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[Any]:
        for e in self._events:
            yield e


class FakeResponses:
    def __init__(self, *, stream_events: list[Any] | None = None, parse_result: Any = None) -> None:
        self._stream_events = stream_events or []
        self._parse_result = parse_result
        self.create_kwargs: dict | None = None
        self.parse_kwargs: dict | None = None

    async def create(self, **kwargs: Any) -> _Stream:
        self.create_kwargs = kwargs
        return _Stream(self._stream_events)

    async def parse(self, **kwargs: Any) -> Any:
        self.parse_kwargs = kwargs
        return self._parse_result


class FakeOpenAIClient:
    def __init__(self, *, stream_events: list[Any] | None = None, parse_result: Any = None) -> None:
        self.responses = FakeResponses(stream_events=stream_events, parse_result=parse_result)
