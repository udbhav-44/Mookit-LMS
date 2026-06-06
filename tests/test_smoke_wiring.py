"""Unblock-kit DoD — the real Orchestrator builds + round-trips on the full fake graph, no network/DB."""

from app.core.orchestrator import Orchestrator
from app.core.reference_resolver import ReferenceResolver
from app.tools.common import ResolveTaxonomyTool, WhoAmITool
from app.tools.echo import EchoTool
from app.tools.registry import ToolRegistry
from tests.core.scripted_llm import ScriptedLLM, prose_round
from tests.fakes.confirm_harness import ConfirmHarness
from tests.fakes.fake_mookit import FakeMooKitClient
from tests.fakes.fake_stores import InMemoryArtifactRegistry, InMemorySessionStore


def _build() -> tuple[Orchestrator, FakeMooKitClient]:
    mookit = FakeMooKitClient()
    sessions = InMemorySessionStore()
    artifacts = InMemoryArtifactRegistry()
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(WhoAmITool(mookit))
    registry.register(ResolveTaxonomyTool(mookit))
    orch = Orchestrator(
        llm=ScriptedLLM([prose_round("hello", response_id="r1")]),
        registry=registry,
        sessions=sessions,
        artifacts=artifacts,
        resolver=ReferenceResolver(artifacts),
        mookit=mookit,
    )
    return orch, mookit


def test_fake_graph_builds(ctx) -> None:
    orch, mookit = _build()
    assert orch and mookit
    assert ctx.tenant_key == "hello.iitk.ac.in:coursetest"
    assert ConfirmHarness(mookit)


async def test_orchestrator_round_trips_on_fakes(ctx) -> None:
    orch, _ = _build()
    events = [e async for e in orch.run_turn(ctx, "hi there")]
    assert events[-1].event == "done"

