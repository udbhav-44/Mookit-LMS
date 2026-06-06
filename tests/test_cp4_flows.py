"""CP4 — all three flows: draft → faithful preview → confirm → live write; nothing writes on generation.

Drives publish tools directly to produce ProposedActions, runs them through the ConfirmHarness (Dev A
gate stand-in), and asserts: (a) propose writes nothing, (b) confirm writes exactly once, (c) editing
after proposal voids the bound hash.
"""

from app.gen.quiz.pipeline import QuizPipeline
from app.tools.announcement import DraftAnnouncementTool, SendAnnouncementTool
from app.tools.assessment import CreateQuizTool, EditQuizTool, PublishAssessmentTool
from app.tools.lecture import DraftLectureTool, PublishLectureTool
from tests.fakes.confirm_harness import ConfirmHarness
from tests.fakes.fake_mookit import FakeMooKitClient
from tests.fakes.fake_rag import retrieve
from tests.fakes.fake_stores import InMemoryArtifactRegistry
from tests.gen.fake_generator import fake_generator


def _pipeline() -> QuizPipeline:
    return QuizPipeline(retrieve=retrieve, generator=fake_generator)


async def test_assessment_flow(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    mookit = FakeMooKitClient()
    harness = ConfirmHarness(mookit)

    create = await CreateQuizTool(_pipeline(), reg).run(
        ctx, {"doc_artifact_id": "doc-1", "title": "Quiz", "count": 2}
    )
    proposal = await PublishAssessmentTool(reg).run(ctx, {"draft_id": create.artifact_id})
    # propose writes nothing
    assert mookit.write_calls == []
    action_id = harness.propose(ctx, proposal)
    await harness.confirm(action_id, current_hash=proposal.content_hash)
    # exactly one assessment created, a section, then its questions added under that section
    assert mookit.write_calls.count("create_assessment") == 1
    assert mookit.write_calls.count("create_section") == 1
    assert mookit.write_calls.count("add_question") == 2


async def test_announcement_flow(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    mookit = FakeMooKitClient()
    harness = ConfirmHarness(mookit)

    d = await DraftAnnouncementTool(reg).run(ctx, {"intent": "Exam tomorrow", "audience": "all"})
    proposal = await SendAnnouncementTool(reg).run(ctx, {"draft_id": d.artifact_id})
    assert mookit.write_calls == []
    aid = harness.propose(ctx, proposal)
    await harness.confirm(aid, current_hash=proposal.content_hash)
    assert mookit.write_calls == ["create_announcement"]


async def test_lecture_flow(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    mookit = FakeMooKitClient()
    harness = ConfirmHarness(mookit)

    d = await DraftLectureTool(mookit, reg).run(
        ctx, {"week_label": "Week 4", "file_artifact_id": "art_9", "file_mookit_id": 55}
    )
    proposal = await PublishLectureTool(reg).run(ctx, {"draft_id": d.artifact_id})
    writes_before = list(mookit.write_calls)
    aid = harness.propose(ctx, proposal)
    await harness.confirm(aid, current_hash=proposal.content_hash)
    new_writes = mookit.write_calls[len(writes_before):]
    assert "create_lecture" in new_writes
    assert "attach_course_resource" in new_writes


async def test_edit_after_proposal_voids_token(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    mookit = FakeMooKitClient()
    harness = ConfirmHarness(mookit)

    create = await CreateQuizTool(_pipeline(), reg).run(
        ctx, {"doc_artifact_id": "doc-1", "title": "Quiz", "count": 2}
    )
    proposal = await PublishAssessmentTool(reg).run(ctx, {"draft_id": create.artifact_id})
    action_id = harness.propose(ctx, proposal)

    # Re-draft after proposing: the new content hash differs from the bound one.
    await EditQuizTool(_pipeline(), reg).run(
        ctx, {"draft_id": create.artifact_id, "op": "add", "qtype": "true_false", "delta": 1}
    )
    new_proposal = await PublishAssessmentTool(reg).run(ctx, {"draft_id": create.artifact_id})
    assert new_proposal.content_hash != proposal.content_hash

    import pytest

    with pytest.raises(ValueError, match="content_hash mismatch"):
        await harness.confirm(action_id, current_hash=new_proposal.content_hash)
    assert mookit.write_calls == []  # nothing published
