"""Adaptive source routing: small docs → full-document comprehension; large → top-k retrieval."""

from app.contracts import RequestContext
from app.gen.quiz.params import QuizParams
from app.gen.quiz.pipeline import QuizPipeline
from tests.fakes.fake_rag import retrieve as fake_retrieve
from tests.fakes.fake_stores import InMemoryArtifactRegistry
from tests.gen.fake_comprehender import fake_comprehender
from tests.gen.fake_generator import fake_generator


def _fetch_all_for(text: str):
    async def _fetch_all(ctx: RequestContext, doc_id: str) -> list[dict]:
        return [{"chunk_index": 0, "text": text, "span": {}, "locator": {}}]

    return _fetch_all


class _SpyComprehender:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, *, sections, params):
        self.calls += 1
        return await fake_comprehender(sections=sections, params=params)


def _spy_retrieve():
    state = {"calls": 0}

    async def _retrieve(ctx, doc_artifact_id, query, k):
        state["calls"] += 1
        return await fake_retrieve(ctx, doc_artifact_id, query, k)

    return _retrieve, state


def _routed_pipeline(text, *, budget, comprehender, retrieve) -> QuizPipeline:
    return QuizPipeline(
        retrieve=retrieve,
        generator=fake_generator,
        comprehender=comprehender,
        fetch_all=_fetch_all_for(text),
        source_routing=True,
        context_token_budget=budget,
    )


async def test_small_doc_routes_to_full_context(ctx: RequestContext, sample_doc_text: str) -> None:
    reg = InMemoryArtifactRegistry()
    comp = _SpyComprehender()
    retrieve, rstate = _spy_retrieve()
    pipe = _routed_pipeline(sample_doc_text, budget=100_000, comprehender=comp, retrieve=retrieve)
    draft = await pipe.build_draft(
        ctx, reg, doc_artifact_id="doc-1", title="Q",
        params=QuizParams(count=3, type_mix={"mcq_single": 3}),
    )
    assert comp.calls == 1       # full-document comprehension was used
    assert rstate["calls"] == 0  # retrieval was NOT used to build the draft
    assert draft.payload["questions"]


async def test_large_doc_routes_to_retrieval(ctx: RequestContext, sample_doc_text: str) -> None:
    reg = InMemoryArtifactRegistry()
    comp = _SpyComprehender()
    retrieve, rstate = _spy_retrieve()
    # A tiny context budget makes even the small sample doc exceed it → RETRIEVAL.
    pipe = _routed_pipeline(sample_doc_text, budget=10, comprehender=comp, retrieve=retrieve)
    draft = await pipe.build_draft(
        ctx, reg, doc_artifact_id="doc-1", title="Q",
        params=QuizParams(count=3, type_mix={"mcq_single": 3}),
    )
    assert comp.calls == 0       # comprehension skipped
    assert rstate["calls"] >= 1  # top-k retrieval used
    assert draft.payload["questions"]


async def test_routing_off_keeps_always_blueprint(ctx: RequestContext, sample_doc_text: str) -> None:
    """Without source_routing, a wired comprehender means always-blueprint (unchanged behavior)."""
    reg = InMemoryArtifactRegistry()
    comp = _SpyComprehender()
    retrieve, rstate = _spy_retrieve()
    pipe = QuizPipeline(
        retrieve=retrieve,
        generator=fake_generator,
        comprehender=comp,
        fetch_all=_fetch_all_for(sample_doc_text),
    )  # source_routing defaults False
    await pipe.build_draft(
        ctx, reg, doc_artifact_id="doc-1", title="Q",
        params=QuizParams(count=2, type_mix={"mcq_single": 2}),
    )
    assert comp.calls == 1
    assert rstate["calls"] == 0
