"""Deterministic per-question quiz-edit endpoint (POST /v1/quiz/{draft_id}/edit).

Boots the real FastAPI app, overrides the request-context dependency, and injects an Orchestrator whose
registry holds a real EditQuizTool over a fake-backed QuizPipeline. Asserts a button-style edit op
applies and the updated draft is returned.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.contracts import RequestContext
from app.core.context import get_request_context
from app.core.orchestrator import Orchestrator
from app.core.reference_resolver import ReferenceResolver
from app.gen.quiz.params import QuizParams
from app.gen.quiz.pipeline import QuizPipeline
from app.main import app
from app.tools.assessment import EditQuizTool
from app.tools.registry import ToolRegistry
from tests.core.scripted_llm import ScriptedLLM
from tests.fakes.fake_mookit import ALL_PERMISSIONS, FakeMooKitClient
from tests.fakes.fake_rag import retrieve
from tests.fakes.fake_stores import InMemoryArtifactRegistry, InMemorySessionStore
from tests.gen.fake_generator import fake_generator

_HEADERS = {"course": "coursetest", "token": "t", "uid": "1"}


def _ctx() -> RequestContext:
    return RequestContext(
        instance_id="hello.iitk.ac.in", course_id="coursetest", user_id=1, session_id="s1",
        forwarded_headers={"course": "coursetest", "token": "t", "uid": "1"},
        permissions=ALL_PERMISSIONS,
    )


@pytest.fixture
def harness():
    artifacts = InMemoryArtifactRegistry()
    pipeline = QuizPipeline(retrieve=retrieve, generator=fake_generator)
    registry = ToolRegistry()
    registry.register(EditQuizTool(pipeline, artifacts))
    orch = Orchestrator(
        llm=ScriptedLLM([]), registry=registry, sessions=InMemorySessionStore(),
        artifacts=artifacts, resolver=ReferenceResolver(artifacts), mookit=FakeMooKitClient(),
    )
    draft = asyncio.run(
        pipeline.build_draft(
            _ctx(), artifacts, doc_artifact_id="doc-1", title="Q",
            params=QuizParams(count=2, type_mix={"mcq_single": 2}),
        )
    )
    app.dependency_overrides[get_request_context] = _ctx
    with TestClient(app) as c:
        c.app.state.orchestrator = orch
        c.app.state.artifact_registry = artifacts
        c.app.state.audit_logger = None
        yield c, draft
    app.dependency_overrides.clear()


def test_flag_op_applies_and_bumps_version(harness):
    client, draft = harness
    resp = client.post(
        f"/v1/quiz/{draft.id}/edit",
        json={"op": "flag", "index": 0, "reason": "ambiguous"},
        headers=_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    j = resp.json()
    assert j["success"] and j["version"] == draft.version + 1
    assert "ambiguous" in j["payload"]["questions"][0]["flags"]


def test_regenerate_op_marks_ai_regenerated(harness):
    client, draft = harness
    resp = client.post(
        f"/v1/quiz/{draft.id}/edit", json={"op": "regenerate", "index": 0}, headers=_HEADERS
    )
    assert resp.status_code == 200, resp.text
    assert "ai_regenerated" in resp.json()["payload"]["questions"][0]["flags"]


def test_edit_text_op_replaces_stem(harness):
    client, draft = harness
    resp = client.post(
        f"/v1/quiz/{draft.id}/edit",
        json={"op": "edit_text", "index": 1, "questionText": "Instructor stem?"},
        headers=_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    q = resp.json()["payload"]["questions"][1]
    assert q["questionText"] == "Instructor stem?" and "human_edited" in q["flags"]


def test_unknown_op_returns_400(harness):
    client, draft = harness
    resp = client.post(f"/v1/quiz/{draft.id}/edit", json={"op": "bogus", "index": 0}, headers=_HEADERS)
    assert resp.status_code == 400
