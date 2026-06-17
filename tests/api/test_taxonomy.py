"""GET /v1/taxonomy/{type} and the batch GET /v1/taxonomy.

Boots the real FastAPI app, overrides the request-context dependency, and injects a fake mooKIT
client. Verifies the response shape, the unknown-type 400, and that a second request is served from
the Redis cache (mooKIT is hit only once) when a cache is present.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.contracts import RequestContext
from app.core.context import get_request_context
from app.main import app
from tests.fakes.fake_mookit import ALL_PERMISSIONS, FakeMooKitClient

_HEADERS = {"course": "coursetest", "token": "t", "uid": "1"}


def _ctx() -> RequestContext:
    return RequestContext(
        instance_id="hello.iitk.ac.in", course_id="coursetest", user_id=1, session_id="s1",
        forwarded_headers={"course": "coursetest", "token": "t", "uid": "1"},
        permissions=ALL_PERMISSIONS, tenant_key="hello.iitk.ac.in:coursetest",
    )


class _FakeRedis:
    """Minimal async get/set with TTL ignored — enough to prove cache hits."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def aclose(self):  # closed by the app lifespan on shutdown
        pass


@pytest.fixture
def client():
    mookit = FakeMooKitClient()
    app.dependency_overrides[get_request_context] = _ctx
    with TestClient(app) as c:
        c.app.state.mookit_client = mookit
        c.app.state.redis = _FakeRedis()
        c.app.state.audit_logger = None
        yield c, mookit
    app.dependency_overrides.clear()


def test_single_type_returns_terms(client):
    c, _ = client
    r = c.get("/v1/taxonomy/week", headers=_HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "week"
    assert {"id": 101, "name": "Week 1"} in body["terms"]
    assert len(body["terms"]) == 4


def test_unknown_type_is_400(client):
    c, _ = client
    r = c.get("/v1/taxonomy/bogus", headers=_HEADERS)
    assert r.status_code == 400


def test_second_request_hits_cache_not_mookit(client):
    c, mookit = client
    c.get("/v1/taxonomy/section", headers=_HEADERS)
    c.get("/v1/taxonomy/section", headers=_HEADERS)
    calls = [rec for rec in mookit.calls if rec[0] == "list_taxonomy" and rec[1].get("type") == "section"]
    assert len(calls) == 1, f"expected one mooKIT call, got {len(calls)}"


def test_batch_returns_all_types(client):
    c, _ = client
    r = c.get("/v1/taxonomy", headers=_HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"week", "module", "topic", "section"}
    assert body["module"] and body["section"]
