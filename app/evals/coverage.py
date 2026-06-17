"""Source-coverage eval — measure how much of a document a quiz is grounded in.

This quantifies the core RAG-vs-full-context quality trade-off rather than asserting it. Two notions:

  candidate coverage — fraction of the document's sections that were AVAILABLE to the generator as
                       grounding evidence. Top-k retrieval can only ground in the k chunks it pulled,
                       so its candidate coverage is bounded by k/N; full-document comprehension sees
                       every section, so its candidate coverage is 1.0. This is the structural reason
                       full-context grounds questions in content retrieval never surfaced.

  citation coverage — fraction of sections actually cited by the produced questions. Bounded by the
                      number of questions, so it is reported (not the headline) and reflects spread.

All scoring is deterministic and offline (no LLM, no tokenizer): sections come from a paragraph-aware
splitter mirroring the RAG chunker's spirit, and matching is verbatim substring overlap on normalized
whitespace — the same grounding contract the pipeline enforces.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

_CHUNK_SIZE = 512
_CHUNK_OVERLAP = 64


class CoverageReport(BaseModel):
    sections_total: int
    sections_covered: int
    distinct_spans: int  # number of unique grounding spans / citation quotes considered
    coverage_ratio: float  # sections_covered / sections_total, in [0, 1]


class CoverageComparison(BaseModel):
    retrieval: CoverageReport
    full_context: CoverageReport

    @property
    def delta(self) -> float:
        """Full-context coverage minus retrieval coverage (positive ⇒ full-context covers more)."""
        return round(self.full_context.coverage_ratio - self.retrieval.coverage_ratio, 4)

    @property
    def full_context_wins(self) -> bool:
        return self.full_context.coverage_ratio >= self.retrieval.coverage_ratio


def _norm(text: str) -> str:
    """Collapse whitespace so verbatim matching is robust to extraction line-wrapping."""
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def section_document(
    doc_text: str, *, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP
) -> list[str]:
    """Split a document into sections (paragraph-aware, size-capped) — the units coverage is measured in.

    Mirrors the RAG chunker: split on blank lines, accumulate up to ~chunk_size chars, and carry a
    small overlap so a section boundary never silently drops a sentence.
    """
    paras = [p.strip() for p in re.split(r"\n{2,}", doc_text or "") if p.strip()]
    sections: list[str] = []
    buf = ""
    for para in paras:
        candidate = f"{buf}\n\n{para}" if buf else para
        if len(candidate) <= chunk_size or not buf:
            buf = candidate
        else:
            sections.append(buf)
            tail = buf[-overlap:] if overlap else ""
            buf = f"{tail}\n\n{para}" if tail else para
    if buf.strip():
        sections.append(buf)
    return sections


def _covered_indices(spans: list[str], sections_norm: list[str]) -> set[int]:
    covered: set[int] = set()
    for raw in spans:
        span = _norm(raw)
        if not span:
            continue
        for i, sec in enumerate(sections_norm):
            # A span covers a section when either contains the other (verbatim grounding contract).
            if span in sec or sec in span:
                covered.add(i)
    return covered


def coverage_of_spans(
    *, spans: list[str], doc_text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP
) -> CoverageReport:
    """Candidate coverage: how much of the document the given grounding spans span."""
    sections = section_document(doc_text, chunk_size=chunk_size, overlap=overlap)
    sections_norm = [_norm(s) for s in sections]
    unique_spans = {_norm(s) for s in spans if _norm(s)}
    covered = _covered_indices(spans, sections_norm)
    total = len(sections)
    return CoverageReport(
        sections_total=total,
        sections_covered=len(covered),
        distinct_spans=len(unique_spans),
        coverage_ratio=round(len(covered) / total, 4) if total else 0.0,
    )


def _question_quotes(question: dict) -> list[str]:
    """All citation quotes attached to a question (single + multi-span)."""
    quotes: list[str] = []
    primary = (question.get("citation") or {}).get("quote")
    if primary:
        quotes.append(primary)
    for cite in question.get("citations") or []:
        q = (cite or {}).get("quote")
        if q:
            quotes.append(q)
    return quotes


def citation_coverage(
    *, questions: list[dict], doc_text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP
) -> CoverageReport:
    """Realized coverage: how much of the document the produced questions actually cite."""
    spans: list[str] = []
    for q in questions:
        spans.extend(_question_quotes(q))
    return coverage_of_spans(spans=spans, doc_text=doc_text, chunk_size=chunk_size, overlap=overlap)


def compare_coverage(
    *,
    retrieval_spans: list[str],
    full_context_spans: list[str],
    doc_text: str,
    chunk_size: int = _CHUNK_SIZE,
    overlap: int = _CHUNK_OVERLAP,
) -> CoverageComparison:
    """Side-by-side candidate coverage for the retrieval pool vs the full-document pool."""
    return CoverageComparison(
        retrieval=coverage_of_spans(
            spans=retrieval_spans, doc_text=doc_text, chunk_size=chunk_size, overlap=overlap
        ),
        full_context=coverage_of_spans(
            spans=full_context_spans, doc_text=doc_text, chunk_size=chunk_size, overlap=overlap
        ),
    )
