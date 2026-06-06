"""B4.4 — hallucination / grounding eval.

Measures the ungrounded-claim rate and citation faithfulness: for each question, does the cited span
actually appear in (support) the retrieved evidence? A fully grounded draft should score ~0 ungrounded.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class GroundingReport(BaseModel):
    total: int
    ungrounded: int
    unfaithful_citations: int

    @property
    def ungrounded_rate(self) -> float:
        return round(self.ungrounded / self.total, 4) if self.total else 0.0

    @property
    def faithful(self) -> bool:
        return self.ungrounded == 0 and self.unfaithful_citations == 0


def measure_grounding(
    questions: list[dict[str, Any]], evidence_texts: list[str]
) -> GroundingReport:
    corpus = "\n".join(t.lower() for t in evidence_texts)
    ungrounded = 0
    unfaithful = 0
    for q in questions:
        cit = q.get("citation") or {}
        quote = (cit.get("quote") or "").strip().lower()
        if not quote:
            ungrounded += 1
            continue
        # Citation is faithful if its quote is supported by the evidence corpus.
        if quote not in corpus and not _overlaps(quote, corpus):
            unfaithful += 1
    return GroundingReport(
        total=len(questions), ungrounded=ungrounded, unfaithful_citations=unfaithful
    )


def _overlaps(quote: str, corpus: str, *, min_ratio: float = 0.6) -> bool:
    """Token-overlap fallback for near-but-not-exact citation matches."""
    q_tokens = {t for t in quote.split() if len(t) > 3}
    if not q_tokens:
        return False
    hits = sum(1 for t in q_tokens if t in corpus)
    return (hits / len(q_tokens)) >= min_ratio
