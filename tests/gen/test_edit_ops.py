"""Phase 2 — per-question edit ops (the affordances the quiz-preview UI dispatches)."""

from app.contracts import RequestContext
from app.gen.quiz.params import QuizParams
from app.gen.quiz.pipeline import QuizPipeline
from tests.fakes.fake_rag import retrieve
from tests.fakes.fake_stores import InMemoryArtifactRegistry
from tests.gen.fake_generator import fake_generator


def _pipeline() -> QuizPipeline:
    return QuizPipeline(retrieve=retrieve, generator=fake_generator)


async def _draft(ctx: RequestContext, reg: InMemoryArtifactRegistry, n: int = 3):
    return await _pipeline().build_draft(
        ctx, reg, doc_artifact_id="doc-1", title="Q", params=QuizParams(count=n, type_mix={"mcq_single": n})
    )


async def test_edit_text_marks_human_edited_and_bumps_version(ctx: RequestContext) -> None:
    reg = InMemoryArtifactRegistry()
    pipe = _pipeline()
    draft = await _draft(ctx, reg)
    updated = await pipe.apply_edit(
        ctx, reg, draft.id, {"op": "edit_text", "index": 0, "questionText": "Instructor-written stem?"}
    )
    q0 = updated.payload["questions"][0]
    assert q0["questionText"] == "Instructor-written stem?"
    assert "human_edited" in q0["flags"]
    assert updated.version == draft.version + 1
    assert updated.provenance["edited_by_human"] is True


async def test_flag_records_reason(ctx: RequestContext) -> None:
    reg = InMemoryArtifactRegistry()
    pipe = _pipeline()
    draft = await _draft(ctx, reg)
    updated = await pipe.apply_edit(ctx, reg, draft.id, {"op": "flag", "index": 1, "reason": "ambiguous"})
    assert "ambiguous" in updated.payload["questions"][1]["flags"]


async def test_regenerate_replaces_and_stays_cited(ctx: RequestContext) -> None:
    reg = InMemoryArtifactRegistry()
    pipe = _pipeline()
    draft = await _draft(ctx, reg)
    updated = await pipe.apply_edit(ctx, reg, draft.id, {"op": "regenerate", "index": 0})
    q0 = updated.payload["questions"][0]
    assert "ai_regenerated" in q0["flags"]
    assert q0["citation"]["quote"].strip()  # still grounded
    assert len(updated.payload["questions"]) == len(draft.payload["questions"])


async def test_replace_similar_flagged(ctx: RequestContext) -> None:
    reg = InMemoryArtifactRegistry()
    pipe = _pipeline()
    draft = await _draft(ctx, reg)
    updated = await pipe.apply_edit(ctx, reg, draft.id, {"op": "replace_similar", "index": 2})
    assert "ai_regenerated" in updated.payload["questions"][2]["flags"]


async def test_change_type_updates_type_and_resyncs_params(ctx: RequestContext) -> None:
    reg = InMemoryArtifactRegistry()
    pipe = _pipeline()
    draft = await _draft(ctx, reg, n=3)
    updated = await pipe.apply_edit(
        ctx, reg, draft.id, {"op": "change_type", "index": 0, "qtype": "true_false"}
    )
    qs = updated.payload["questions"]
    assert qs[0]["questionType"] == "true_false"
    # params.type_mix is rebuilt from the actual questions and stays consistent with count.
    params = updated.payload["params"]
    assert sum(params["type_mix"].values()) == params["count"] == len(qs)
    assert params["type_mix"].get("true_false") == 1


async def test_unknown_op_still_rejected(ctx: RequestContext) -> None:
    reg = InMemoryArtifactRegistry()
    pipe = _pipeline()
    draft = await _draft(ctx, reg)
    import pytest

    with pytest.raises(ValueError):
        await pipe.apply_edit(ctx, reg, draft.id, {"op": "bogus", "index": 0})
