"""Phase 2 integration — the blueprint-first build_draft path (comprehend → plan → multi-span gen)."""

from app.contracts import RequestContext
from app.gen.quiz.blueprint import (
    BloomCount,
    Blueprint,
    ConceptNode,
    LearningObjective,
)
from app.gen.quiz.params import QuizParams
from app.gen.quiz.pipeline import QuizPipeline
from tests.fakes.fake_rag import retrieve
from tests.fakes.fake_stores import InMemoryArtifactRegistry
from tests.gen.fake_comprehender import fake_comprehender
from tests.gen.fake_generator import fake_generator


def _fetch_all_for(text: str):
    async def _fetch_all(ctx: RequestContext, doc_id: str) -> list[dict]:
        return [{"chunk_index": 0, "text": text, "span": {}, "locator": {}}]

    return _fetch_all


def _blueprint_pipeline(text: str, comprehender=fake_comprehender) -> QuizPipeline:
    return QuizPipeline(
        retrieve=retrieve,
        generator=fake_generator,
        comprehender=comprehender,
        fetch_all=_fetch_all_for(text),
    )


async def test_blueprint_path_generates_grounded_cited_questions(
    ctx: RequestContext, sample_doc_text: str
) -> None:
    reg = InMemoryArtifactRegistry()
    pipe = _blueprint_pipeline(sample_doc_text)
    draft = await pipe.build_draft(
        ctx, reg, doc_artifact_id="doc-1", title="Photosynthesis",
        params=QuizParams(count=3, type_mix={"mcq_single": 3}),
    )
    qs = draft.payload["questions"]
    assert qs, "blueprint path should produce questions"
    for q in qs:
        assert q["citation"]["source_id"] == "doc-1"
        assert q["citation"]["quote"].strip()
        assert q["citations"], "multi-span citations populated on the new path"
        # Every citation quote is verbatim-grounded in the source.
        assert q["citation"]["quote"] in " ".join(sample_doc_text.split())


async def test_blueprint_path_respects_count(ctx: RequestContext, sample_doc_text: str) -> None:
    reg = InMemoryArtifactRegistry()
    pipe = _blueprint_pipeline(sample_doc_text)
    draft = await pipe.build_draft(
        ctx, reg, doc_artifact_id="doc-1", title="Q",
        params=QuizParams(count=4, type_mix={"mcq_single": 4}),
    )
    assert len(draft.payload["questions"]) == 4


async def test_blueprint_path_no_text_yields_no_questions(ctx: RequestContext) -> None:
    reg = InMemoryArtifactRegistry()
    pipe = _blueprint_pipeline("")  # fetch_all returns an empty document
    draft = await pipe.build_draft(
        ctx, reg, doc_artifact_id="doc-1", title="Q", params=QuizParams()
    )
    assert draft.payload["questions"] == []
    assert "no_source_evidence" in draft.payload["warnings"]


# --- Engineering: a quantitative concept must yield a numeric-capable (fib) item ---------------

_ENG_TEXT = "Newton's second law states that F = m a. For m = 2 and a = 3 the force is 6."


async def _eng_comprehender(*, sections, params) -> Blueprint:
    return Blueprint(
        objectives=[
            LearningObjective(id="o1", statement="Apply Newton's second law", bloom="apply", concept_ids=["c1"])
        ],
        concepts=[
            ConceptNode(
                id="c1",
                name="Newton's second law",
                summary="F = m a",
                kind="quantitative",
                representative_quote="Newton's second law states that F = m a.",
                suggested_bloom=["apply"],
                formulas=["F = m a"],
                units=["N"],
            )
        ],
        suggested_distribution=[BloomCount(bloom="apply", count=1)],
        quantitative_ratio=1.0,
    )


async def test_quantitative_concept_produces_verified_numeric_item(ctx: RequestContext) -> None:
    reg = InMemoryArtifactRegistry()
    pipe = _blueprint_pipeline(_ENG_TEXT, comprehender=_eng_comprehender)
    draft = await pipe.build_draft(
        ctx, reg, doc_artifact_id="doc-1", title="Mechanics",
        params=QuizParams(count=2, bloom_level="apply", type_mix={"mcq_single": 2}),
    )
    qs = draft.payload["questions"]
    assert qs
    # Quantitative slots are steered to fib (numeric-capable), even though the mix asked for mcq_single.
    assert all(q["questionType"] == "fib" for q in qs)
    # Each carries a checkable worked solution that the pipeline recomputed and verified.
    for q in qs:
        assert q["solution"] is not None
        assert "numeric_unverified" not in q["flags"]
        assert "numeric_missing_solution" not in q["flags"]


async def test_postprocess_flags_wrong_numeric_answer(ctx: RequestContext) -> None:
    """A solution whose stated answer contradicts its own expression is flagged."""
    from app.gen.quiz.schemas import FIB, Citation, SolutionSpec, VarBinding

    pipe = QuizPipeline(retrieve=retrieve, generator=fake_generator)
    bad = FIB(
        questionText="m=2, a=3 → force?",
        citation=Citation(source_id="doc-1", locator={}, quote="F = m a"),
        fibUseRange=True, fibRangeLower=99.0, fibRangeUpper=99.0,
        solution=SolutionSpec(
            solution_expr="m * a",
            variables=[VarBinding(name="m", value=2.0), VarBinding(name="a", value=3.0)],
            answer=99.0,  # wrong: m*a = 6, not 99
            unit="N",
        ),
    )
    processed = await pipe._postprocess(bad, [])
    assert "numeric_unverified" in processed.flags


# --- Multi-PDF: a concept whose quote lives in doc-b must cite doc-b ---------------------------


async def test_multi_pdf_attributes_citation_to_correct_source(ctx: RequestContext) -> None:
    reg = InMemoryArtifactRegistry()
    text_a = "Alpha document. The Calvin cycle occurs in the stroma."
    text_b = "Beta document. Chlorophyll a reflects green light to plants."

    async def fetch_all(c: RequestContext, doc_id: str) -> list[dict]:
        return [{"chunk_index": 0, "text": text_a if doc_id == "doc-a" else text_b}]

    async def comp(*, sections, params) -> Blueprint:
        return Blueprint(
            objectives=[LearningObjective(id="o1", statement="x", bloom="remember", concept_ids=["c1"])],
            concepts=[
                ConceptNode(id="c1", name="Pigment", summary="s", representative_quote="Chlorophyll a reflects green light to plants.")
            ],
        )

    pipe = QuizPipeline(retrieve=retrieve, generator=fake_generator, comprehender=comp, fetch_all=fetch_all)
    draft = await pipe.build_draft(
        ctx, reg, doc_artifact_id=["doc-a", "doc-b"], title="Combined",
        params=QuizParams(count=1, type_mix={"mcq_single": 1}),
    )
    qs = draft.payload["questions"]
    assert qs and qs[0]["citation"]["source_id"] == "doc-b"  # quote came from doc-b


async def test_legacy_path_unchanged_without_comprehender(ctx: RequestContext) -> None:
    reg = InMemoryArtifactRegistry()
    pipe = QuizPipeline(retrieve=retrieve, generator=fake_generator)  # no comprehender → legacy
    draft = await pipe.build_draft(
        ctx, reg, doc_artifact_id="doc-1", title="Q",
        params=QuizParams(count=2, type_mix={"mcq_single": 2}),
    )
    assert len(draft.payload["questions"]) == 2
