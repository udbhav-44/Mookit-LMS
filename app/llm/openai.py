"""OpenAIProvider over the Responses API (Dev B), conforming to the canonical LLMProvider contract.

``respond()`` streams OpenAI Responses semantic events and translates them into the canonical
generic ``LLMEvent(event_type, data)`` stream via ``StreamTranslator`` (pure, unit-testable).
``respond_structured()`` uses ``responses.parse`` with a Pydantic schema and handles refusals +
length truncation explicitly.

Emitted ``event_type`` values (data shape in parentheses):
    assistant_delta        ({"text": str})
    tool_call_started      ({"call_id": str, "name": str})
    tool_call_args_delta   ({"call_id": str, "delta": str})
    tool_call_args_done    ({"call_id": str, "name": str, "arguments": dict})
    response_completed     ({"response_id": str, "usage": dict | None})
    error                  ({"code": str, "message": str, "retryable": bool})

The OpenAI client is injected so tests can drive the translator with synthetic events without network.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel

from app.contracts.llm import LLMEvent, LLMProvider
from app.llm.events import ModelRefusal, OutputTruncated


class StreamTranslator:
    """Translate OpenAI Responses streaming events → canonical LLMEvent stream.

    Stateful across a single stream: ``output_item.added`` for a function_call gives us the
    ``call_id``/``name`` which later ``function_call_arguments.*`` events reference by ``item_id``.
    """

    def __init__(self) -> None:
        self._item_to_call: dict[str, tuple[str, str]] = {}  # item_id -> (call_id, name)

    def feed(self, event: Any) -> list[LLMEvent]:
        etype = getattr(event, "type", None)
        if etype == "response.output_item.added":
            return self._on_item_added(event)
        if etype == "response.output_text.delta":
            return [LLMEvent(event_type="assistant_delta", data={"text": getattr(event, "delta", "") or ""})]
        if etype == "response.function_call_arguments.delta":
            return self._on_args_delta(event)
        if etype == "response.function_call_arguments.done":
            return self._on_args_done(event)
        if etype == "response.completed":
            return self._on_completed(event)
        if etype == "error":
            return [
                LLMEvent(
                    event_type="error",
                    data={
                        "code": getattr(event, "code", "stream_error") or "stream_error",
                        "message": str(getattr(event, "message", "stream error")),
                        "retryable": True,
                    },
                )
            ]
        return []

    def _on_item_added(self, event: Any) -> list[LLMEvent]:
        item = getattr(event, "item", None)
        if item is None or getattr(item, "type", None) != "function_call":
            return []
        item_id = getattr(item, "id", "") or ""
        call_id = getattr(item, "call_id", item_id) or item_id
        name = getattr(item, "name", "") or ""
        self._item_to_call[item_id] = (call_id, name)
        return [LLMEvent(event_type="tool_call_started", data={"call_id": call_id, "name": name})]

    def _on_args_delta(self, event: Any) -> list[LLMEvent]:
        item_id = getattr(event, "item_id", "") or ""
        call_id, _name = self._item_to_call.get(item_id, (item_id, ""))
        return [
            LLMEvent(
                event_type="tool_call_args_delta",
                data={"call_id": call_id, "delta": getattr(event, "delta", "") or ""},
            )
        ]

    def _on_args_done(self, event: Any) -> list[LLMEvent]:
        item_id = getattr(event, "item_id", "") or ""
        call_id, name = self._item_to_call.get(item_id, (item_id, ""))
        raw = getattr(event, "arguments", "") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            args = {}
        return [
            LLMEvent(
                event_type="tool_call_args_done",
                data={"call_id": call_id, "name": name, "arguments": args},
            )
        ]

    def _on_completed(self, event: Any) -> list[LLMEvent]:
        response = getattr(event, "response", None)
        response_id = getattr(response, "id", "") or ""
        usage_obj = getattr(response, "usage", None)
        usage: dict[str, Any] | None = None
        if usage_obj is not None:
            if hasattr(usage_obj, "model_dump"):
                usage = usage_obj.model_dump()
            elif isinstance(usage_obj, dict):
                usage = usage_obj
        return [LLMEvent(event_type="response_completed", data={"response_id": response_id, "usage": usage})]


class OpenAIProvider(LLMProvider):
    def __init__(self, client: Any, *, default_model: str = "gpt-4o") -> None:
        self._client = client
        self._model = default_model

    def respond(
        self,
        *,
        instructions: str,
        input: list[dict],
        tools: list[dict],
        tool_choice: str = "auto",
        parallel_tool_calls: bool = True,
        previous_response_id: str | None = None,
        stream: bool = True,
        prompt_cache_key: str | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[LLMEvent]:
        return self._stream(
            instructions=instructions,
            input=input,
            tools=tools,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
            previous_response_id=previous_response_id,
            prompt_cache_key=prompt_cache_key,
            temperature=temperature,
        )

    async def _stream(
        self,
        *,
        instructions: str,
        input: list[dict],
        tools: list[dict] | None,
        tool_choice: str,
        parallel_tool_calls: bool,
        previous_response_id: str | None,
        prompt_cache_key: str | None,
        temperature: float | None,
    ) -> AsyncIterator[LLMEvent]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "instructions": instructions,
            "input": input,
            "stream": True,
            "tool_choice": tool_choice,
            "parallel_tool_calls": parallel_tool_calls,
        }
        if tools:
            kwargs["tools"] = tools
        if previous_response_id:
            kwargs["previous_response_id"] = previous_response_id
        if prompt_cache_key:
            kwargs["prompt_cache_key"] = prompt_cache_key
        if temperature is not None:
            kwargs["temperature"] = temperature

        translator = StreamTranslator()
        try:
            stream = await self._client.responses.create(**kwargs)
            async for event in stream:
                for translated in translator.feed(event):
                    yield translated
        except Exception as exc:  # noqa: BLE001 — surface as an event, never crash the stream
            yield LLMEvent(event_type="error", data={"code": "provider_error", "message": str(exc), "retryable": True})

    async def respond_structured(
        self,
        *,
        instructions: str,
        input: list[dict],
        schema: type[BaseModel],
        prompt_cache_key: str | None = None,
        temperature: float | None = None,
    ) -> BaseModel:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "instructions": instructions,
            "input": input,
            "text_format": schema,
        }
        if prompt_cache_key:
            kwargs["prompt_cache_key"] = prompt_cache_key
        if temperature is not None:
            kwargs["temperature"] = temperature

        response = await self._client.responses.parse(**kwargs)

        if getattr(response, "status", None) == "incomplete":
            reason = getattr(getattr(response, "incomplete_details", None), "reason", "")
            if reason == "max_output_tokens":
                raise OutputTruncated()

        refusal = _extract_refusal(response)
        if refusal is not None:
            raise ModelRefusal(refusal)

        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise OutputTruncated("no parsed output returned")
        return parsed


def _extract_refusal(response: Any) -> str | None:
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            if getattr(content, "type", None) == "refusal":
                return getattr(content, "refusal", "refused")
    return None
