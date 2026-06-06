"""End-to-end SSE wiring test: Dev B orchestrator → Dev A /v1/chat (no Redis/Postgres/OpenAI).

Boots the real FastAPI app, then overrides the request-context dependency, stubs the rate limiter,
and injects a ScriptedLLM-backed Orchestrator. Asserts the SSE stream carries the orchestrator's
events (assistant_delta … done, and pending_confirmation for a publish proposal).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api.chat as chat_module
from app.contracts import PreviewRender, ProposedAction, RequestContext, Tool
from app.core.context import get_request_context
from app.core.orchestrator import Orchestrator
from app.core.reference_resolver import ReferenceResolver
from app.llm.schema import strict_schema
from app.main import app
from app.tools.echo import EchoArgs, EchoTool
from app.tools.registry import ToolRegistry
from tests.core.scripted_llm import ScriptedLLM, prose_round, tool_round
from tests.fakes.confirm_harness import canonical_hash
from tests.fakes.fake_mookit import ALL_PERMISSIONS, FakeMooKitClient
from tests.fakes.fake_stores import InMemoryArtifactRegistry, InMemorySessionStore


def _ctx() -> RequestContext:
    return RequestContext(
        instance_id="hello.iitk.ac.in", course_id="coursetest", user_id=1, session_id="s1",
        forwarded_headers={"course": "coursetest", "token": "t", "uid": "1"},
        permissions=ALL_PERMISSIONS,
    )


class _PublishTool(Tool):
    name = "send_announcement"
    description = "publish"
    risk_tier = "publish"
    parameters_schema = strict_schema(EchoArgs)
    required_permission = ("announcements", "publish")

    async def run(self, ctx: RequestContext, args: dict[str, Any]) -> ProposedAction:
        payload = {"title": "x", "type": "normal", "notifyMail": 0, "published": {"status": 1}}
        return ProposedAction(
            action="send_announcement", target_ref={}, payload=payload,
            preview=PreviewRender(title="Send announcement", summary_lines=["To: all"]),
            content_hash=canonical_hash(payload),
        )


def _orchestrator(rounds) -> Orchestrator:
    artifacts = InMemoryArtifactRegistry()
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(_PublishTool())
    return Orchestrator(
        llm=ScriptedLLM(rounds),
        registry=registry,
        sessions=InMemorySessionStore(),
        artifacts=artifacts,
        resolver=ReferenceResolver(artifacts),
        mookit=FakeMooKitClient(),
    )


@pytest.fixture
def client(monkeypatch):
    async def _noop_rate_limit(*a, **k):
        return None

    monkeypatch.setattr(chat_module, "check_rate_limit", _noop_rate_limit)
    app.dependency_overrides[get_request_context] = _ctx
    with TestClient(app) as c:
        app.state.audit_logger = None
        yield c
    app.dependency_overrides.clear()


def test_chat_streams_prose(client):
    client.app.state.orchestrator = _orchestrator([prose_round("Hello!", response_id="r1")])
    resp = client.post(
        "/v1/chat",
        json={"message": "hi", "sessionId": "s1"},
        headers={"course": "coursetest", "token": "t", "uid": "1"},
    )
    assert resp.status_code == 200
    body = resp.text
    assert "assistant_delta" in body and "Hello!" in body
    assert "event: done" in body


def test_chat_streams_pending_confirmation(client):
    rounds = [tool_round(name="send_announcement", call_id="c1", arguments={"text": "x"}, response_id="r1")]
    client.app.state.orchestrator = _orchestrator(rounds)
    resp = client.post(
        "/v1/chat",
        json={"message": "cancel class", "sessionId": "s1"},
        headers={"course": "coursetest", "token": "t", "uid": "1"},
    )
    assert resp.status_code == 200
    assert "pending_confirmation" in resp.text
    assert "send_announcement" in resp.text
