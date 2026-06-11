"""Phase 3 — independent solve-by-evidence critique.

The deterministic numeric check (``numeric.verify_numeric``) catches when a stated answer contradicts
its own worked expression, but not a *wrong formula* or a flawed line of reasoning. This critique
closes that gap: an independent model re-derives the answer from the cited evidence ALONE and compares
it to the question's answer key. It RAISES FLAGS for human review — it never auto-approves and never
mutates the question (matching the existing ``CritiqueFn`` contract consumed by ``verify.py``).

Grounded by construction: the evidence is spotlighted as untrusted data (same injection defense as
generation), and the model is told to use only that evidence — important for novel/unpublished
research where it can't fall back on prior knowledge.
"""

from __future__ import annotations

import secrets
from typing import Literal

from pydantic import BaseModel

from app.contracts import LLMProvider
from app.gen.quiz.prompting import spotlight_evidence
from app.gen.quiz.rag import Evidence
from app.gen.quiz.schemas import (
    FIB,
    Descriptive,
    MCQMulti,
    MCQSingle,
    TrueFalse,
    _QuestionBase,
)


class SolveVerdict(BaseModel):
    answerable_from_evidence: bool
    derived_answer: str  # what the evidence alone supports
    agrees_with_key: bool  # does the derived answer match the question's stated key?
    ambiguity: Literal["none", "multiple_defensible", "underspecified"]
    confidence: float
    reason: str


SOLVE_SYSTEM = (
    "You are an exacting engineering teaching assistant checking a quiz question. Using ONLY the "
    "supplied source evidence (not prior knowledge — the material may be novel research), decide "
    "whether the question is answerable, derive the answer yourself, and compare it to the proposed "
    "answer key. Report disagreements and ambiguities honestly; you are a reviewer, not an author."
)


def _answer_key_summary(q: _QuestionBase) -> str:
    """A compact description of the question's intended answer, for the critique to check against."""
    if isinstance(q, MCQSingle):
        correct = [o.optionText for o in q.options if o.isCorrect]
        return f"correct option: {correct}"
    if isinstance(q, MCQMulti):
        correct = [o.optionText for o in q.options if o.isCorrect]
        return f"correct options: {correct}"
    if isinstance(q, TrueFalse):
        return f"answer: {'True' if q.trueFalseAnswer == 1 else 'False'}"
    if isinstance(q, FIB):
        if q.solution is not None:
            return f"numeric answer: {q.solution.answer} {q.solution.unit or ''}".strip()
        if q.fibUseRange:
            return f"accepted range: [{q.fibRangeLower}, {q.fibRangeUpper}]"
        answers = [a.answerText for b in (q.blanks or []) for a in b.answers]
        return f"accepted blank answers: {answers}"
    if isinstance(q, Descriptive):
        return "(open-ended; graded by rubric — judge answerability/clarity, not a single key)"
    return "(unknown)"


def build_solve_prompt(q: _QuestionBase, evidence: list[Evidence], *, delimiter: str) -> str:
    return "\n".join(
        [
            "Question:",
            q.questionText,
            "",
            f"Proposed answer key — {_answer_key_summary(q)}",
            "",
            "Derive the answer from the evidence below ALONE. If the evidence does not determine an "
            "answer, set answerable_from_evidence to false. For open-ended questions, agrees_with_key "
            "may be true if a defensible answer exists.",
            "",
            spotlight_evidence(evidence, delimiter=delimiter),
        ]
    )


class LLMSolveCritique:
    """A ``CritiqueFn``: independently solves from evidence and flags disagreements for review."""

    def __init__(self, provider: LLMProvider, *, temperature: float = 0.0) -> None:
        self._provider = provider
        self._temperature = temperature

    async def __call__(self, question: _QuestionBase, evidence: list[Evidence]) -> list[str]:
        if not evidence:
            return []
        prompt = build_solve_prompt(question, evidence, delimiter=secrets.token_hex(4))
        try:
            verdict = await self._provider.respond_structured(
                instructions=SOLVE_SYSTEM,
                input=[{"role": "user", "content": prompt}],
                schema=SolveVerdict,
                temperature=self._temperature,
            )
        except Exception:  # noqa: BLE001 — a verifier failure must not crash generation
            return []
        return _verdict_to_flags(verdict, is_descriptive=isinstance(question, Descriptive))


def _verdict_to_flags(verdict: SolveVerdict, *, is_descriptive: bool) -> list[str]:
    flags: list[str] = []
    if not verdict.answerable_from_evidence:
        flags.append("unsolvable_from_evidence")
    # Key agreement is meaningless for open-ended items.
    elif not is_descriptive and not verdict.agrees_with_key:
        flags.append("solve_disagreement")
    if verdict.ambiguity != "none":
        flags.append("ambiguous")
    return flags
