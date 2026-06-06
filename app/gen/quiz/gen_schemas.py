"""Generation-only schemas (what the LLM produces).

These are the CONTENT fields only — no ``citation`` and no ``flags``. Grounding is enforced
server-side: the pipeline attaches the citation from the chosen evidence span, so the model never
supplies (and cannot fabricate) a source locator. Keeping these free of the open ``dict`` locator also
satisfies OpenAI strict Structured Outputs (which forbids free-form objects).

Each gen model maps 1:1 to a full model in ``schemas.py`` via ``to_full(...)``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from app.gen.quiz.schemas import (
    FIB,
    Blank,
    BloomLevel,
    Citation,
    Descriptive,
    MCQMulti,
    MCQSingle,
    Option,
    QuestionType,
    TrueFalse,
    _QuestionBase,
)


class GenMCQSingle(BaseModel):
    questionText: str  # noqa: N815
    bloom_level: BloomLevel
    options: list[Option]


class GenMCQMulti(BaseModel):
    questionText: str  # noqa: N815
    bloom_level: BloomLevel
    options: list[Option]
    allowPartialMarks: bool = False  # noqa: N815


class GenTrueFalse(BaseModel):
    questionText: str  # noqa: N815
    bloom_level: BloomLevel
    trueFalseAnswer: Literal[0, 1]  # noqa: N815


class GenFIB(BaseModel):
    questionText: str  # noqa: N815
    bloom_level: BloomLevel
    blanks: list[Blank] | None = None
    fibUseRange: bool = False  # noqa: N815
    fibRangeLower: float | None = None  # noqa: N815
    fibRangeUpper: float | None = None  # noqa: N815


class GenDescriptive(BaseModel):
    questionText: str  # noqa: N815
    bloom_level: BloomLevel


GEN_SCHEMA_BY_TYPE: dict[str, type[BaseModel]] = {
    "mcq_single": GenMCQSingle,
    "mcq_multi": GenMCQMulti,
    "true_false": GenTrueFalse,
    "fib": GenFIB,
    "descriptive": GenDescriptive,
}

# A placeholder citation; the pipeline replaces it with the server-chosen evidence span.
_PLACEHOLDER_CITATION = Citation(source_id="pending", locator={}, quote="pending")


def to_full(qtype: QuestionType, gen: BaseModel, *, score: float = 1.0) -> _QuestionBase:
    """Build the validated full question model from a generation result + a placeholder citation."""
    data: dict[str, Any] = {**gen.model_dump(), "score": score, "citation": _PLACEHOLDER_CITATION}
    full_by_type: dict[str, type[_QuestionBase]] = {
        "mcq_single": MCQSingle,
        "mcq_multi": MCQMulti,
        "true_false": TrueFalse,
        "fib": FIB,
        "descriptive": Descriptive,
    }
    return full_by_type[qtype].model_validate(data)
