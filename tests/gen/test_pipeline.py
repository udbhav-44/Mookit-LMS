"""B2.8 acceptance (CP3) — end-to-end grounded draft; all 5 types; citation invariant; edits bump version."""

from app.contracts import RequestContext
from app.gen.quiz.params import QuizParams
from app.gen.quiz.pipeline import QuizPipeline
from tests.fakes.fake_rag import retrieve
from tests.fakes.fake_stores import InMemoryArtifactRegistry
from tests.gen.fake_generator import fake_generator


def _pipeline() -> QuizPipeline:
    return QuizPipeline(retrieve=retrieve, generator=fake_generator)


def _all_types_params() -> QuizParams:
    mix = {"mcq_single": 1, "mcq_multi": 1, "true_false": 1, "fib": 1, "descriptive": 1}
    return QuizParams(count=5, type_mix=mix)


async def test_build_draft_all_five_types(ctx: RequestContext) -> None:
    reg = InMemoryArtifactRegistry()
    draft = await _pipeline().build_draft(
        ctx, reg, doc_artifact_id="doc-1", title="Photosynthesis Quiz", params=_all_types_params()
    )
    assert draft.type == "assessment_draft"
    questions = draft.payload["questions"]
    assert len(questions) == 5
    types = {q["questionType"] for q in questions}
    assert types == {"mcq_single", "mcq_multi", "true_false", "fib", "descriptive"}


async def test_every_question_is_cited(ctx: RequestContext) -> None:
    reg = InMemoryArtifactRegistry()
    draft = await _pipeline().build_draft(
        ctx, reg, doc_artifact_id="doc-1", title="Q", params=_all_types_params()
    )
    for q in draft.payload["questions"]:
        cit = q["citation"]
        assert cit["source_id"] == "doc-1"
        assert cit["quote"].strip()  # non-empty grounded span
        assert cit["locator"].get("doc_id") == "sample"


async def test_descriptive_gets_rubric(ctx: RequestContext) -> None:
    reg = InMemoryArtifactRegistry()
    draft = await _pipeline().build_draft(
        ctx, reg, doc_artifact_id="doc-1", title="Q", params=_all_types_params()
    )
    desc = next(q for q in draft.payload["questions"] if q["questionType"] == "descriptive")
    assert desc["rubric"] is not None
    assert sum(c["points"] for c in desc["rubric"]["criteria"]) == desc["score"]


async def test_multi_doc_draft_cites_each_source(ctx: RequestContext) -> None:
    reg = InMemoryArtifactRegistry()
    params = QuizParams(count=4, type_mix={"mcq_single": 4})
    draft = await _pipeline().build_draft(
        ctx,
        reg,
        doc_artifact_id=["doc-a", "doc-b"],
        title="Combined Quiz",
        params=params,
    )
    assert draft.payload["source_artifact_ids"] == ["doc-a", "doc-b"]
    source_ids = {q["citation"]["source_id"] for q in draft.payload["questions"]}
    assert source_ids <= {"doc-a", "doc-b"}
    assert len(source_ids) == 2


async def test_provenance_stamped(ctx: RequestContext) -> None:
    reg = InMemoryArtifactRegistry()
    draft = await _pipeline().build_draft(
        ctx, reg, doc_artifact_id="doc-1", title="Q", params=QuizParams()
    )
    assert draft.provenance["ai_generated"] is True
    assert draft.provenance["edited_by_human"] is False
    assert "doc-1" in draft.provenance["source_ids"]


async def test_no_evidence_yields_no_questions(ctx: RequestContext) -> None:
    reg = InMemoryArtifactRegistry()
    draft = await _pipeline().build_draft(
        ctx, reg, doc_artifact_id="missing", title="Q", params=QuizParams()
    )
    assert draft.payload["questions"] == []
    assert "no_source_evidence" in draft.payload["warnings"]


async def test_higher_order_flagged_for_review(ctx: RequestContext) -> None:
    reg = InMemoryArtifactRegistry()
    params = QuizParams(bloom_level="analyze", count=1, type_mix={"mcq_single": 1})
    draft = await _pipeline().build_draft(ctx, reg, doc_artifact_id="doc-1", title="Q", params=params)
    q = draft.payload["questions"][0]
    assert "higher_order_review" in q["flags"]
    assert any("higher-order" in w for w in draft.payload["warnings"])


async def test_add_more_bumps_version_and_preserves(ctx: RequestContext) -> None:
    reg = InMemoryArtifactRegistry()
    pipe = _pipeline()
    draft = await pipe.build_draft(
        ctx, reg, doc_artifact_id="doc-1", title="Q", params=QuizParams(count=1, type_mix={"mcq_single": 1})
    )
    before = len(draft.payload["questions"])
    updated = await pipe.apply_edit(ctx, reg, draft.id, {"op": "add", "qtype": "true_false", "delta": 3})
    assert updated.version == draft.version + 1
    assert len(updated.payload["questions"]) == before + 3
    assert updated.provenance["edited_by_human"] is True
    # original questions preserved
    assert updated.payload["questions"][0]["questionType"] == "mcq_single"


async def test_remove_and_set_difficulty(ctx: RequestContext) -> None:
    reg = InMemoryArtifactRegistry()
    pipe = _pipeline()
    draft = await pipe.build_draft(
        ctx, reg, doc_artifact_id="doc-1", title="Q", params=_all_types_params()
    )
    removed = await pipe.apply_edit(ctx, reg, draft.id, {"op": "remove", "index": 0})
    assert len(removed.payload["questions"]) == 4
    harder = await pipe.apply_edit(ctx, reg, draft.id, {"op": "set_difficulty", "difficulty": "hard"})
    assert harder.payload["params"]["difficulty"] == "hard"
