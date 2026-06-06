"""B2.5 — multi-stage verification.

Screens the 4 hallucination classes: reasoning_inconsistency, insolvability, factual_error,
math_error. Rule-based checks run first; an optional LLM critique (injected seam) adds flags. The
critique RAISES FLAGS FOR THE HUMAN — it is never the final judge and never auto-approves.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from app.gen.quiz.rag import Evidence
from app.gen.quiz.schemas import (
    FIB,
    Descriptive,
    MCQMulti,
    MCQSingle,
    TrueFalse,
    _QuestionBase,
)

FlagType = str  # "reasoning_inconsistency" | "insolvability" | "factual_error" | "math_error" | ...


class VerificationReport(BaseModel):
    flags: list[str]
    passed: bool  # True iff no flags from the rule-based + critique stages

    @property
    def requires_review(self) -> bool:
        return not self.passed


class CritiqueFn(Protocol):
    async def __call__(self, question: _QuestionBase, evidence: list[Evidence]) -> list[str]: ...


async def verify_question(
    question: _QuestionBase,
    evidence: list[Evidence],
    *,
    critique: CritiqueFn | None = None,
) -> VerificationReport:
    flags = list(_rule_based(question))
    if critique is not None:
        flags.extend(await critique(question, evidence))
    # Higher-order Bloom is always routed to human review (known ~65% alignment weakness).
    if question.is_higher_order:
        flags.append("higher_order_review")
    return VerificationReport(flags=flags, passed=len(flags) == 0)


def _rule_based(question: _QuestionBase) -> list[str]:
    flags: list[str] = []

    # Grounding: every question must cite a non-empty source span.
    if not question.citation.quote.strip():
        flags.append("ungrounded")

    if isinstance(question, MCQSingle):
        if sum(1 for o in question.options if o.isCorrect) != 1:
            flags.append("reasoning_inconsistency")  # no single answer ⇒ insoluble as single-select
    elif isinstance(question, MCQMulti):
        if not any(o.isCorrect for o in question.options):
            flags.append("insolvability")  # nothing correct to select
    elif isinstance(question, TrueFalse):
        if question.trueFalseAnswer not in (0, 1):
            flags.append("insolvability")
    elif isinstance(question, FIB):
        if question.fibUseRange:
            lo, hi = question.fibRangeLower, question.fibRangeUpper
            if lo is None or hi is None or lo > hi:
                flags.append("math_error")
        elif not question.blanks or any(not b.answers for b in question.blanks):
            flags.append("insolvability")
    elif isinstance(question, Descriptive):
        if question.rubric is None:
            flags.append("insolvability")  # ungradeable without a rubric

    return flags


def check_answer_grounded_in_evidence(question: _QuestionBase, evidence: list[Evidence]) -> bool:
    """Heuristic factual check: the cited quote should appear in the retrieved evidence text."""
    quote = question.citation.quote.strip().lower()
    if not quote:
        return False
    return any(quote in e.text.lower() or e.text.lower() in quote for e in evidence)
