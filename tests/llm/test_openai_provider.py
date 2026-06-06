"""B0.2 acceptance — event translation (prose + tool-call turns), refusal, truncation."""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.contracts.types import (
    AssistantDelta,
    ResponseCompleted,
    ToolCallArgsDone,
    ToolCallStarted,
)
from app.llm.events import ModelRefusal, OutputTruncated
from app.llm.openai_provider import OpenAIProvider, StreamTranslator
from tests.llm.fake_openai import (
    FakeOpenAIClient,
    args_delta,
    args_done,
    completed,
    function_call_item,
    text_delta,
)


async def _collect(provider: OpenAIProvider, **kwargs) -> list:
    return [e async for e in provider.respond(instructions="sys", input=[], **kwargs)]


async def test_prose_only_turn() -> None:
    events = [text_delta("Hel"), text_delta("lo"), completed(response_id="resp_1")]
    provider = OpenAIProvider(FakeOpenAIClient(stream_events=events), default_model="gpt-4o")
    out = await _collect(provider)
    assert [type(e) for e in out] == [AssistantDelta, AssistantDelta, ResponseCompleted]
    assert "".join(e.text for e in out if isinstance(e, AssistantDelta)) == "Hello"
    assert out[-1].response_id == "resp_1"


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
    started = [e for e in out if isinstance(e, ToolCallStarted)]
    done = [e for e in out if isinstance(e, ToolCallArgsDone)]
    assert started and started[0].name == "create_quiz" and started[0].call_id == "call_1"
    assert done and done[0].arguments == {"count": 5}
    assert done[0].call_id == "call_1" and done[0].name == "create_quiz"


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
    done = [e for e in out if isinstance(e, ToolCallArgsDone)]
    assert done[0].arguments == {}


class _Schema(BaseModel):
    answer: str


async def test_respond_structured_returns_parsed() -> None:
    parsed = _Schema(answer="42")
    result_obj = SimpleNamespace(status="completed", output=[], output_parsed=parsed)
    provider = OpenAIProvider(
        FakeOpenAIClient(parse_result=result_obj), default_model="gpt-4o"
    )
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
