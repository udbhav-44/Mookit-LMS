"""B1.1 acceptance — prose turn, tool round-trip, propose-not-execute, parallel flag, unknown tool."""

from typing import Any

from app.contracts.types import (
    PreviewRender,
    ProposedAction,
    RequestContext,
    Tool,
)
from app.core.orchestrator import Orchestrator
from app.core.reference_resolver import ReferenceResolver
from app.llm.schema import strict_schema
from app.tools.echo import EchoArgs, EchoTool
from app.tools.registry import ToolRegistry
from tests.core.scripted_llm import ScriptedLLM, prose_round, tool_round
from tests.fakes.confirm_harness import canonical_hash
from tests.fakes.fake_mookit import FakeMooKitClient
from tests.fakes.fake_stores import InMemoryArtifactRegistry, InMemorySessionStore


class _PublishTool(Tool):
    name = "publish_thing"
    description = "publish"
    risk_tier = "publish"
    parameters_schema = strict_schema(EchoArgs)
    required_permission = ("announcements", "publish")  # present in the test ctx permissions

    async def run(self, ctx: RequestContext, args: dict[str, Any]) -> ProposedAction:
        payload = {"thing": args.get("text", "")}
        return ProposedAction(
            action="publish_thing",
            target_ref={"id": 1},
            payload=payload,
            preview=PreviewRender(title="Publish thing"),
            content_hash=canonical_hash(payload),
        )


def _make(llm: ScriptedLLM, *, tools: list[Tool], perms) -> tuple[Orchestrator, FakeMooKitClient]:
    registry = ToolRegistry()
    for t in tools:
        registry.register(t)
    sessions = InMemorySessionStore()
    artifacts = InMemoryArtifactRegistry()
    mookit = FakeMooKitClient()
    orch = Orchestrator(
        llm=llm,
        registry=registry,
        sessions=sessions,
        artifacts=artifacts,
        resolver=ReferenceResolver(artifacts),
        mookit=mookit,
    )
    return orch, mookit


async def _drain(orch, ctx, text):
    return [e async for e in orch.run_turn(ctx, text)]


async def test_prose_only_turn(ctx: RequestContext) -> None:
    from app.contracts.types import PermissionMatrix

    llm = ScriptedLLM([prose_round("Hello there", response_id="r1")])
    orch, _ = _make(llm, tools=[EchoTool()], perms=PermissionMatrix())
    events = await _drain(orch, ctx, "hi")
    kinds = [e.event for e in events]
    assert "assistant_delta" in kinds
    assert kinds[-1] == "done"
    assert events[-1].data["response_id"] == "r1"


async def test_tool_round_trips(ctx: RequestContext) -> None:
    llm = ScriptedLLM(
        [
            tool_round(name="echo", call_id="c1", arguments={"text": "ping"}, response_id="r1"),
            prose_round("done echoing", response_id="r2"),
        ]
    )
    orch, _ = _make(llm, tools=[EchoTool()], perms=ctx.permissions)
    events = await _drain(orch, ctx, "echo ping")
    kinds = [e.event for e in events]
    assert "tool_started" in kinds
    assert kinds[-1] == "done"
    # second respond call carried the function_call_output back to the model
    second_call_input = llm.calls[1]["input"]
    assert any(i.get("type") == "function_call_output" for i in second_call_input)


async def test_publish_tool_proposes_not_executes(ctx: RequestContext) -> None:
    llm = ScriptedLLM(
        [tool_round(name="publish_thing", call_id="c1", arguments={"text": "x"}, response_id="r1")]
    )
    orch, mookit = _make(llm, tools=[EchoTool(), _PublishTool()], perms=ctx.permissions)
    events = await _drain(orch, ctx, "publish it")
    kinds = [e.event for e in events]
    assert "pending_confirmation" in kinds
    # The model loop never called a mooKIT write.
    assert mookit.write_calls == []
    pc = next(e for e in events if e.event == "pending_confirmation")
    assert pc.data["action"] == "publish_thing"
    assert "content_hash" in pc.data


async def test_parallel_disabled_when_mutating_tool_visible(ctx: RequestContext) -> None:
    llm = ScriptedLLM([prose_round("hi", response_id="r1")])
    orch, _ = _make(llm, tools=[EchoTool(), _PublishTool()], perms=ctx.permissions)
    await _drain(orch, ctx, "hello")
    assert llm.calls[0]["parallel_tool_calls"] is False


async def test_parallel_enabled_when_only_read_tools(ctx: RequestContext) -> None:
    from app.contracts.types import PermissionMatrix

    llm = ScriptedLLM([prose_round("hi", response_id="r1")])
    orch, _ = _make(llm, tools=[EchoTool()], perms=PermissionMatrix())
    await _drain(orch, ctx, "hello")
    assert llm.calls[0]["parallel_tool_calls"] is True


async def test_unknown_tool_emits_error_and_continues(ctx: RequestContext) -> None:
    llm = ScriptedLLM(
        [
            tool_round(name="ghost", call_id="c1", arguments={}, response_id="r1"),
            prose_round("recovered", response_id="r2"),
        ]
    )
    orch, _ = _make(llm, tools=[EchoTool()], perms=ctx.permissions)
    events = await _drain(orch, ctx, "call ghost")
    kinds = [e.event for e in events]
    assert "error" in kinds
    assert kinds[-1] == "done"
