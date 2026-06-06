"""B3.1 acceptance — propose-not-execute, preview warnings, hash stability, edit changes hash."""

from app.contracts import ProposedAction, ToolResult
from app.gen.quiz.pipeline import QuizPipeline
from app.tools.assessment import (
    CreateQuizTool,
    EditQuizTool,
    PublishAssessmentTool,
)
from tests.fakes.fake_rag import retrieve
from tests.fakes.fake_stores import InMemoryArtifactRegistry
from tests.gen.fake_generator import fake_generator


def _pipeline() -> QuizPipeline:
    return QuizPipeline(retrieve=retrieve, generator=fake_generator)


async def _make_draft(ctx, reg, *, count=3, bloom="understand"):
    tool = CreateQuizTool(_pipeline(), reg)
    res = await tool.run(
        ctx, {"doc_artifact_id": "doc-1", "title": "Quiz", "count": count, "bloom_level": bloom}
    )
    assert isinstance(res, ToolResult) and res.artifact_id
    return res.artifact_id


async def test_create_quiz_makes_draft(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    aid = await _make_draft(ctx, reg)
    draft = await reg.get(ctx, aid)
    assert draft and len(draft.payload["questions"]) == 3


async def test_publish_proposes_never_executes(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    aid = await _make_draft(ctx, reg)
    result = await PublishAssessmentTool(reg).run(ctx, {"draft_id": aid})
    assert isinstance(result, ProposedAction)
    assert result.action == "publish_assessment"
    # Created as a draft (status 0); the executor flips to 1 after questions are added.
    assert result.payload["assessment"]["published"]["status"] == 0
    assert result.payload["_type"] == "quizzes"
    # citations carried alongside for audit/provenance
    assert result.payload["citations"][0]["source_id"] == "doc-1"
    # each question body is QuestionCreate-compatible (has published)
    assert result.payload["questions"][0]["published"]["status"] == 1


async def test_preview_warns_on_higher_order(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    aid = await _make_draft(ctx, reg, count=1, bloom="analyze")
    result = await PublishAssessmentTool(reg).run(ctx, {"draft_id": aid})
    assert any("higher-order" in w for w in result.preview.warnings)


async def test_hash_stable_and_changes_on_edit(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    aid = await _make_draft(ctx, reg)
    pub = PublishAssessmentTool(reg)
    h1 = (await pub.run(ctx, {"draft_id": aid})).content_hash
    h1b = (await pub.run(ctx, {"draft_id": aid})).content_hash
    assert h1 == h1b  # stable for identical payload
    await EditQuizTool(_pipeline(), reg).run(
        ctx, {"draft_id": aid, "op": "add", "qtype": "true_false", "delta": 2}
    )
    h2 = (await pub.run(ctx, {"draft_id": aid})).content_hash
    assert h2 != h1  # editing the draft changes the bound hash
