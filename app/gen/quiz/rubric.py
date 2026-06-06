"""B2.6 — rubric generation for descriptive questions.

Produces a grounded scoring rubric whose points sum to the question score. The generator is an
injected seam; a deterministic default builds a sensible rubric offline so the pipeline is testable
without an LLM.
"""

from __future__ import annotations

from typing import Protocol

from app.gen.quiz.rag import Evidence
from app.gen.quiz.schemas import Descriptive, Rubric, RubricCriterion


class RubricGenerator(Protocol):
    async def __call__(self, *, stem: str, evidence: list[Evidence], total: float) -> Rubric: ...


async def generate_rubric(
    *,
    stem: str,
    evidence: list[Evidence],
    total: float,
    generator: RubricGenerator | None = None,
) -> Rubric:
    if generator is not None:
        return await generator(stem=stem, evidence=evidence, total=total)
    return _default_rubric(total=total)


def _default_rubric(*, total: float) -> Rubric:
    """Two-criterion rubric splitting the score between correctness and explanation."""
    correctness = round(total * 0.6, 6)
    explanation = round(total - correctness, 6)
    return Rubric(
        criteria=[
            RubricCriterion(
                name="Correctness",
                descriptor="States the correct concept grounded in the source material.",
                points=correctness,
            ),
            RubricCriterion(
                name="Explanation",
                descriptor="Explains the reasoning clearly and completely.",
                points=explanation,
            ),
        ],
        total=total,
    )


def attach_rubric(question: Descriptive, rubric: Rubric) -> Descriptive:
    return question.model_copy(update={"rubric": rubric})
