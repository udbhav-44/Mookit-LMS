"""UK.5 — shared pytest fixtures: a ready RequestContext + wired fakes + sample docs."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.contracts.types import RequestContext
from tests.fakes.confirm_harness import ConfirmHarness
from tests.fakes.fake_mookit import ALL_PERMISSIONS, FakeMooKitClient
from tests.fakes.fake_stores import InMemoryArtifactRegistry, InMemorySessionStore

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def ctx() -> RequestContext:
    return RequestContext(
        instance_id="hello.iitk.ac.in",
        course_id="coursetest",
        user_id=1,
        session_id="sess-1",
        forwarded_headers={"course": "coursetest", "token": "jwt", "uid": "1"},
        permissions=ALL_PERMISSIONS,
        request_id="req-1",
    )


@pytest.fixture
def mookit() -> FakeMooKitClient:
    return FakeMooKitClient()


@pytest.fixture
def sessions() -> InMemorySessionStore:
    return InMemorySessionStore()


@pytest.fixture
def artifacts() -> InMemoryArtifactRegistry:
    return InMemoryArtifactRegistry()


@pytest.fixture
def confirm(mookit: FakeMooKitClient) -> ConfirmHarness:
    return ConfirmHarness(mookit)


@pytest.fixture
def sample_doc_text() -> str:
    return (FIXTURES / "sample.pdf.txt").read_text(encoding="utf-8")


@pytest.fixture
def injection_doc_text() -> str:
    return (FIXTURES / "injection_doc.txt").read_text(encoding="utf-8")
