"""Source-coverage eval: measures the RAG-vs-full-context grounding gap rather than asserting it."""

from app.contracts import RequestContext
from app.evals.coverage import (
    citation_coverage,
    compare_coverage,
    coverage_of_spans,
    section_document,
)
from app.gen.quiz.rag import gather_evidence
from tests.fakes.fake_rag import retrieve

# 8 short, distinct paragraphs → 8 sections at a small chunk size.
_DOC = "\n\n".join(f"Section {i}: topic number {i} explains idea {i} in detail." for i in range(8))
_OPTS = {"chunk_size": 60, "overlap": 0}


def test_section_document_splits_into_paragraphs() -> None:
    assert len(section_document(_DOC, **_OPTS)) == 8


def test_full_context_covers_more_than_topk() -> None:
    secs = section_document(_DOC, **_OPTS)
    k = 4
    # Top-k retrieval surfaced only the first k sections; full-document comprehension saw all of them.
    cmp = compare_coverage(
        retrieval_spans=secs[:k], full_context_spans=list(secs), doc_text=_DOC, **_OPTS
    )
    assert cmp.retrieval.coverage_ratio == 0.5  # 4/8
    assert cmp.full_context.coverage_ratio == 1.0  # 8/8
    assert cmp.full_context_wins
    assert cmp.delta == 0.5


def test_coverage_of_spans_counts_distinct_sections() -> None:
    secs = section_document(_DOC, **_OPTS)
    rep = coverage_of_spans(spans=[secs[0], secs[0], secs[3]], doc_text=_DOC, **_OPTS)
    assert rep.sections_total == 8
    assert rep.sections_covered == 2  # section 0 (deduped) + section 3
    assert rep.distinct_spans == 2
    assert rep.coverage_ratio == round(2 / 8, 4)


def test_citation_coverage_from_questions() -> None:
    secs = section_document(_DOC, **_OPTS)
    questions = [
        {"citation": {"quote": secs[1]}, "citations": [{"quote": secs[2]}]},
        {"citation": {"quote": secs[5]}},
    ]
    rep = citation_coverage(questions=questions, doc_text=_DOC, **_OPTS)
    assert rep.sections_covered == 3  # sections 1, 2, 5
    assert rep.coverage_ratio == round(3 / 8, 4)


def test_no_citations_is_zero_coverage() -> None:
    rep = citation_coverage(questions=[{"questionText": "ungrounded"}], doc_text=_DOC, **_OPTS)
    assert rep.sections_covered == 0
    assert rep.coverage_ratio == 0.0


async def test_pipeline_pools_full_context_beats_retrieval(
    ctx: RequestContext, sample_doc_text: str
) -> None:
    """End-to-end measurement on the real sample doc: the retrieval grounding pool (top-k) covers a
    strict subset of the document, while the full-document pool covers all of it."""
    opts = {"chunk_size": 160, "overlap": 0}
    spans = await gather_evidence(retrieve, ctx, "doc-1", topics=None, k=2)
    retrieval_spans = [e.text for e in spans]
    full_spans = section_document(sample_doc_text, **opts)

    cmp = compare_coverage(
        retrieval_spans=retrieval_spans,
        full_context_spans=full_spans,
        doc_text=sample_doc_text,
        **opts,
    )
    assert cmp.full_context.coverage_ratio == 1.0
    assert cmp.retrieval.coverage_ratio < 1.0  # top-k cannot ground in what it never retrieved
    assert cmp.full_context_wins
