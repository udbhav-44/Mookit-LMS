"""UK.1 acceptance — the 7 contracts import cleanly and round-trip."""

import pytest
from pydantic import ValidationError

from app.contracts import (
    Artifact,
    PermissionMatrix,
    PreviewRender,
    ProposedAction,
    RequestContext,
    ToolResult,
)


def test_request_context_derives_tenant_key() -> None:
    ctx = RequestContext(
        instance_id="hello.iitk.ac.in",
        course_id="cs101",
        user_id=1,
        session_id="abc123",
    )
    assert ctx.tenant_key == "hello.iitk.ac.in:cs101"


def test_request_context_keeps_explicit_tenant_key() -> None:
    ctx = RequestContext(
        instance_id="i",
        course_id="c",
        user_id=1,
        session_id="s",
        tenant_key="custom",
    )
    assert ctx.tenant_key == "custom"


def test_permission_matrix_has_permission() -> None:
    pm = PermissionMatrix(resources={"lectures": ["create", "list"]})
    assert pm.has_permission("lectures", "create")
    assert not pm.has_permission("lectures", "publish")
    assert not pm.has_permission("assessments", "create")


def test_artifact_type_rejects_unknown() -> None:
    with pytest.raises(ValidationError):
        Artifact(id="1", type="bogus_type", title="t", status="draft")  # type: ignore[arg-type]


def test_tool_result_round_trip() -> None:
    r = ToolResult(ok=True, data={"x": 1}, artifact_id="a1")
    assert ToolResult.model_validate(r.model_dump()) == r


def test_proposed_action_round_trip() -> None:
    pa = ProposedAction(
        action="publish_assessment",
        target_ref={"assessment_type": "quizzes", "assessment_id": 5},
        payload={"title": "Q1"},
        preview=PreviewRender(title="Publish quiz", summary_lines=["10 questions"]),
        content_hash="deadbeef",
    )
    assert ProposedAction.model_validate(pa.model_dump()) == pa
