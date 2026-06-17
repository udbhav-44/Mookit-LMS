"""ask_user tool + orchestrator clarification flow."""

from typing import Any

from app.contracts import (
    ClarificationRequest,
    PermissionMatrix,
    RequestContext,
)
from app.core.orchestrator import Orchestrator
from app.core.reference_resolver import ReferenceResolver
from app.tools.ask_user import AskUserTool
from app.tools.registry import ToolRegistry
from tests.core.scripted_llm import ScriptedLLM, tool_round
from tests.fakes.fake_mookit import FakeMooKitClient
from tests.fakes.fake_stores import InMemoryArtifactRegistry, InMemorySessionStore


async def test_ask_user_returns_clarification_request(ctx: RequestContext) -> None:
    tool = AskUserTool()
    result = await tool.run(
        ctx,
        {
            "preamble": "Need a detail",
            "questions": [
                {
                    "id": "question_count",
                    "prompt": "How many questions?",
                    "options": [{"id": "five", "label": "5"}, {"id": "ten", "label": "10"}],
                    "allow_multiple": False,
                    "allow_free_text": True,
                }
            ],
        },
    )
    assert isinstance(result, ClarificationRequest)
    assert result.preamble == "Need a detail"
    assert result.questions[0].options[1].label == "10"


def _make(llm: ScriptedLLM, sessions: InMemorySessionStore) -> Orchestrator:
    registry = ToolRegistry()
    registry.register(AskUserTool())
    artifacts = InMemoryArtifactRegistry()
    return Orchestrator(
        llm=llm,
        registry=registry,
        sessions=sessions,
        artifacts=artifacts,
        resolver=ReferenceResolver(artifacts),
        mookit=FakeMooKitClient(),
    )


async def test_clarification_event_ends_turn_and_persists(ctx: RequestContext) -> None:
    args: dict[str, Any] = {
        "preamble": None,
        "questions": [
            {
                "id": "qcount",
                "prompt": "How many questions?",
                "options": [{"id": "ten", "label": "10"}],
                "allow_multiple": False,
                "allow_free_text": True,
            }
        ],
    }
    llm = ScriptedLLM([tool_round(name="ask_user", call_id="c1", arguments=args, response_id="r1")])
    sessions = InMemorySessionStore()
    orch = _make(llm, sessions)
    events = [e async for e in orch.run_turn(ctx, "make a quiz")]
    kinds = [e.event for e in events]
    assert "clarification" in kinds
    assert kinds[-1] == "done"
    clar = next(e for e in events if e.event == "clarification")
    assert clar.data["questions"][0]["prompt"] == "How many questions?"
    # The asked question is persisted so the next user turn (the answer) keeps context.
    transcript = await sessions.get_transcript(ctx, max_tokens=10_000)
    assert any("How many questions?" in m.content for m in transcript if m.role == "assistant")
