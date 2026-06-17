"""POST /v1/lecture/{draft_id}/edit — re-resolve week/module against live taxonomy.

Boots the real app with an in-memory registry + fake mooKIT (whose taxonomy has Week 1–4), seeds a
lecture_draft, and asserts editing the week re-resolves to the real id and that an unknown week 400s.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.contracts import Artifact, RequestContext
from app.core.context import get_request_context
from app.gen.provenance import stamp
from app.main import app
from tests.fakes.fake_mookit import ALL_PERMISSIONS, FakeMooKitClient
from tests.fakes.fake_stores import InMemoryArtifactRegistry

_HEADERS = {"course": "coursetest", "token": "t", "uid": "1"}


def _ctx() -> RequestContext:
    return RequestContext(
        instance_id="hello.iitk.ac.in", course_id="coursetest", user_id=1, session_id="s1",
        forwarded_headers={"course": "coursetest", "token": "t", "uid": "1"},
        permissions=ALL_PERMISSIONS, tenant_key="hello.iitk.ac.in:coursetest",
    )


@pytest.fixture
def client():
    artifacts = InMemoryArtifactRegistry()
    draft = Artifact(
        id="", type="lecture_draft", title="Lecture — Week 4", status="draft",
        payload={"title": "Lecture — Week 4", "week_label": "Week 4", "week_id": 104,
                 "module_label": None, "topic_id": None, "file_artifact_id": "f1",
                 "file_mookit_id": 555, "release_on": None, "description": None},
        provenance=stamp(ai_generated=True, edited_by_human=False, source_ids=["f1"]),
    )
    draft_id = asyncio.run(artifacts.add(_ctx(), draft))
    app.dependency_overrides[get_request_context] = _ctx
    with TestClient(app) as c:
        c.app.state.artifact_registry = artifacts
        c.app.state.mookit_client = FakeMooKitClient()
        c.app.state.audit_logger = None
        yield c, draft_id
    app.dependency_overrides.clear()


def test_edit_reresolves_week(client):
    c, draft_id = client
    r = c.post(f"/v1/lecture/{draft_id}/edit", json={"week_label": "Week 2"}, headers=_HEADERS)
    assert r.status_code == 200, r.text
    payload = r.json()["payload"]
    assert payload["week_label"] == "Week 2"
    assert payload["week_id"] == 102  # fake taxonomy: Week i -> 100 + i
    assert payload["file_mookit_id"] == 555  # preserved


def test_edit_unknown_week_is_400(client):
    c, draft_id = client
    r = c.post(f"/v1/lecture/{draft_id}/edit", json={"week_label": "Week 99"}, headers=_HEADERS)
    assert r.status_code == 400
