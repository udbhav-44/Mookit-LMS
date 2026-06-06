"""B4.3 — quiz-quality eval harness.

Rubric scoring across dimensions (understandability, relevance, grammar, clarity, answerability, Bloom
alignment) on a fixed doc set, plus regression comparison vs a checked-in baseline. LLM evaluators are
treated as FLAGGERS (they misalign with experts) — we report scores, never auto-gate on them.

The scorer is an injected seam: a deterministic structural scorer runs offline; an LLM-backed scorer
is used in the live eval suite.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel

DIMENSIONS = [
    "understandability",
    "relevance",
    "grammar",
    "clarity",
    "answerability",
    "bloom_alignment",
]


class QualityReport(BaseModel):
    scores: dict[str, float]  # dimension -> [0, 1]
    per_question: list[dict[str, Any]]
    flagged_count: int

    @property
    def overall(self) -> float:
        return round(sum(self.scores.values()) / len(self.scores), 4) if self.scores else 0.0


class Regression(BaseModel):
    deltas: dict[str, float]
    regressed: list[str]  # dimensions that dropped beyond tolerance

    @property
    def has_regression(self) -> bool:
        return bool(self.regressed)


class Scorer(Protocol):
    async def __call__(self, *, question: dict[str, Any], doc_text: str) -> dict[str, float]: ...


async def score_quiz(
    *,
    questions: list[dict[str, Any]],
    doc_text: str,
    scorer: Scorer | None = None,
) -> QualityReport:
    scorer = scorer or _structural_scorer
    per_q: list[dict[str, Any]] = []
    totals = dict.fromkeys(DIMENSIONS, 0.0)
    flagged = 0
    for q in questions:
        s = await scorer(question=q, doc_text=doc_text)
        per_q.append({"questionType": q.get("questionType"), "scores": s})
        for dim in DIMENSIONS:
            totals[dim] += s.get(dim, 0.0)
        if q.get("flags"):
            flagged += 1
    n = max(len(questions), 1)
    scores = {dim: round(totals[dim] / n, 4) for dim in DIMENSIONS}
    return QualityReport(scores=scores, per_question=per_q, flagged_count=flagged)


def baseline_compare(report: QualityReport, baseline: dict[str, float], *, tol: float = 0.05) -> Regression:
    deltas = {dim: round(report.scores.get(dim, 0.0) - baseline.get(dim, 0.0), 4) for dim in DIMENSIONS}
    regressed = [dim for dim, d in deltas.items() if d < -tol]
    return Regression(deltas=deltas, regressed=regressed)


async def _structural_scorer(*, question: dict[str, Any], doc_text: str) -> dict[str, float]:
    """Deterministic, offline proxy scorer (no LLM). Good enough to detect gross regressions."""
    text = question.get("questionText", "")
    cited = bool(question.get("citation", {}).get("quote"))
    answerable = _looks_answerable(question)
    grounded = cited and question.get("citation", {}).get("quote", "").lower() in doc_text.lower()
    return {
        "understandability": 1.0 if 10 <= len(text) <= 300 else 0.5,
        "relevance": 1.0 if grounded else 0.4,
        "grammar": 1.0 if text.strip().endswith(("?", ".", "_")) or "_" in text else 0.7,
        "clarity": 1.0 if len(text.split()) >= 3 else 0.3,
        "answerability": 1.0 if answerable else 0.0,
        "bloom_alignment": 0.65 if question.get("bloom_level") in {"analyze", "evaluate", "create"} else 0.9,
    }


def _looks_answerable(q: dict[str, Any]) -> bool:
    t = q.get("questionType")
    if t == "mcq_single":
        return sum(1 for o in q.get("options", []) if o.get("isCorrect")) == 1
    if t == "mcq_multi":
        return any(o.get("isCorrect") for o in q.get("options", []))
    if t == "true_false":
        return q.get("trueFalseAnswer") in (0, 1)
    if t == "fib":
        return bool(q.get("blanks")) or bool(q.get("fibUseRange"))
    if t == "descriptive":
        return q.get("rubric") is not None
    return False
