"""Phase 1 — comprehension blueprint + grounding + source routing."""

from app.gen.quiz.blueprint import ground_blueprint
from app.gen.quiz.params import QuizParams
from app.gen.quiz.source_router import SourceMode, estimate_tokens, route
from tests.gen.fake_comprehender import blueprint_with_ungrounded, fake_comprehender

# ---------------------------------------------------------------------------
# Source router
# ---------------------------------------------------------------------------


def test_router_small_single_doc_is_full_context() -> None:
    # ~5k tokens, one doc, 100k budget → fits comfortably.
    assert route(total_chars=20_000, n_docs=1, context_token_budget=100_000) == SourceMode.FULL_CONTEXT


def test_router_large_single_doc_is_sectioned() -> None:
    # ~90k tokens > 60% of 100k budget, but < 4x → map-reduce.
    assert route(total_chars=360_000, n_docs=1, context_token_budget=100_000) == SourceMode.SECTIONED


def test_router_multi_doc_never_full_context() -> None:
    assert route(total_chars=20_000, n_docs=3, context_token_budget=100_000) == SourceMode.SECTIONED


def test_router_huge_corpus_is_retrieval() -> None:
    assert route(total_chars=5_000_000, n_docs=50, context_token_budget=100_000) == SourceMode.RETRIEVAL


def test_estimate_tokens() -> None:
    assert estimate_tokens("abcd" * 10) == 10


# ---------------------------------------------------------------------------
# Comprehension + grounding
# ---------------------------------------------------------------------------


async def test_fake_comprehender_produces_coverable_blueprint(sample_doc_text: str) -> None:
    bp = await fake_comprehender(sections=[sample_doc_text], params=QuizParams())
    assert len(bp.concepts) >= 3
    assert len(bp.objectives) >= 2
    assert sum(d.count for d in bp.suggested_distribution) >= 1
    # Misconceptions are present to seed distractors (item-quality goal).
    assert any(c.common_misconceptions for c in bp.concepts)


async def test_grounding_keeps_verbatim_concepts(sample_doc_text: str) -> None:
    bp = await fake_comprehender(sections=[sample_doc_text], params=QuizParams())
    grounded = ground_blueprint(bp, source_text=sample_doc_text, source_doc_id="doc-1")
    assert len(grounded.concepts) == len(bp.concepts)  # all quotes are verbatim
    assert not grounded.warnings
    for gc in grounded.concepts:
        cit = gc.citation
        assert cit.source_id == "doc-1"
        assert cit.quote.strip()
        # The locator offsets slice the normalized source back to the cited quote.
        assert "char_start" in cit.locator and "char_end" in cit.locator


async def test_grounding_drops_ungrounded_concept_and_objective(sample_doc_text: str) -> None:
    bp = blueprint_with_ungrounded()
    grounded = ground_blueprint(bp, source_text=sample_doc_text, source_doc_id="doc-1")
    kept_ids = {gc.concept.id for gc in grounded.concepts}
    assert "c9" not in kept_ids  # fabricated quote not in source
    assert "c1" in kept_ids
    assert any("c9" in w for w in grounded.warnings)
    # The objective that referenced only the dropped concept is gone too.
    assert all(o.id != "o9" for o in grounded.objectives)


async def test_grounding_offsets_roundtrip(sample_doc_text: str) -> None:
    import re

    bp = await fake_comprehender(sections=[sample_doc_text], params=QuizParams())
    grounded = ground_blueprint(bp, source_text=sample_doc_text, source_doc_id="doc-1")
    # Normalize the source the same way grounding does, then confirm offsets point at the quote.
    norm = re.sub(r"\s+", " ", sample_doc_text).strip()
    for gc in grounded.concepts:
        s, e = gc.citation.locator["char_start"], gc.citation.locator["char_end"]
        assert norm[s:e] == gc.citation.quote
