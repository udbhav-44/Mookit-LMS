"""OpenAIProvider acceptance — event translation (prose + tool-call), refusal, truncation.

Asserts the canonical generic LLMEvent(event_type, data) stream.
"""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.llm.events import ModelRefusal, OutputTruncated
from app.llm.openai import OpenAIProvider, StreamTranslator
from tests.llm.fake_openai import (
    FakeOpenAIClient,
    args_delta,
    args_done,
    completed,
    function_call_item,
    text_delta,
)


async def _collect(provider: OpenAIProvider, **kwargs) -> list:
    return [e async for e in provider.respond(instructions="sys", input=[], tools=[], **kwargs)]


async def test_prose_only_turn() -> None:
    events = [text_delta("Hel"), text_delta("lo"), completed(response_id="resp_1")]
    provider = OpenAIProvider(FakeOpenAIClient(stream_events=events), default_model="gpt-4o")
    out = await _collect(provider)
    types = [e.event_type for e in out]
    assert types == ["assistant_delta", "assistant_delta", "response_completed"]
    assert "".join(e.data["text"] for e in out if e.event_type == "assistant_delta") == "Hello"
    assert out[-1].data["response_id"] == "resp_1"


async def test_tool_call_turn() -> None:
    events = [
        function_call_item(item_id="it_1", call_id="call_1", name="create_quiz"),
        args_delta(item_id="it_1", delta='{"count":'),
        args_delta(item_id="it_1", delta=" 5}"),
        args_done(item_id="it_1", arguments='{"count": 5}'),
        completed(response_id="resp_2"),
    ]
    provider = OpenAIProvider(FakeOpenAIClient(stream_events=events), default_model="gpt-4o")
    out = await _collect(provider)
    started = [e for e in out if e.event_type == "tool_call_started"]
    done = [e for e in out if e.event_type == "tool_call_args_done"]
    assert started and started[0].data["name"] == "create_quiz" and started[0].data["call_id"] == "call_1"
    assert done and done[0].data["arguments"] == {"count": 5}
    assert done[0].data["call_id"] == "call_1" and done[0].data["name"] == "create_quiz"


def test_translator_ignores_unknown_events() -> None:
    t = StreamTranslator()
    assert t.feed(SimpleNamespace(type="response.unknown.event")) == []


async def test_create_receives_tool_choice_and_parallel_flag() -> None:
    client = FakeOpenAIClient(stream_events=[completed(response_id="r")])
    provider = OpenAIProvider(client, default_model="gpt-4o")
    await _collect(provider, parallel_tool_calls=False, prompt_cache_key="k1")
    assert client.responses.create_kwargs["parallel_tool_calls"] is False
    assert client.responses.create_kwargs["prompt_cache_key"] == "k1"


async def test_args_done_bad_json_yields_empty_dict() -> None:
    events = [
        function_call_item(item_id="it_1", call_id="c1", name="t"),
        args_done(item_id="it_1", arguments="not json"),
    ]
    provider = OpenAIProvider(FakeOpenAIClient(stream_events=events), default_model="gpt-4o")
    out = await _collect(provider)
    done = [e for e in out if e.event_type == "tool_call_args_done"]
    assert done[0].data["arguments"] == {}


class _Schema(BaseModel):
    answer: str


async def test_respond_structured_returns_parsed() -> None:
    parsed = _Schema(answer="42")
    result_obj = SimpleNamespace(status="completed", output=[], output_parsed=parsed)
    provider = OpenAIProvider(FakeOpenAIClient(parse_result=result_obj), default_model="gpt-4o")
    got = await provider.respond_structured(instructions="s", input=[], schema=_Schema)
    assert got == parsed


async def test_respond_structured_raises_on_refusal() -> None:
    refusal_content = SimpleNamespace(type="refusal", refusal="cannot help")
    item = SimpleNamespace(content=[refusal_content])
    result_obj = SimpleNamespace(status="completed", output=[item], output_parsed=None)
    provider = OpenAIProvider(FakeOpenAIClient(parse_result=result_obj), default_model="gpt-4o")
    with pytest.raises(ModelRefusal):
        await provider.respond_structured(instructions="s", input=[], schema=_Schema)


async def test_respond_structured_raises_on_truncation() -> None:
    result_obj = SimpleNamespace(
        status="incomplete",
        incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        output=[],
        output_parsed=None,
    )
    provider = OpenAIProvider(FakeOpenAIClient(parse_result=result_obj), default_model="gpt-4o")
    with pytest.raises(OutputTruncated):
        await provider.respond_structured(instructions="s", input=[], schema=_Schema)
