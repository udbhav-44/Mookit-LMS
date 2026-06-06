"""B2.3 — per-type structured schemas + validation, mapped to mooKIT question types.

Each model:
  * validates its type-specific invariants (e.g. mcq_single has exactly one correct option),
  * carries a source-span ``citation`` (grounding invariant),
  * exposes ``to_mookit_payload()`` producing the exact mooKIT request body field names from
    docs/plan/09-mookit-api-reference.md.

Bloom levels follow the 6-level taxonomy; higher-order (analyze/evaluate/create) is routed to
mandatory human review at assembly time.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

BloomLevel = Literal["remember", "understand", "apply", "analyze", "evaluate", "create"]
HIGHER_ORDER: set[str] = {"analyze", "evaluate", "create"}

QuestionType = Literal["mcq_single", "mcq_multi", "true_false", "fib", "descriptive"]


class Citation(BaseModel):
    """A source-span citation that grounds a question."""

    source_id: str  # the document/artifact id
    locator: dict[str, Any]  # e.g. {"page": 2, "char_start": 0, "char_end": 170}
    quote: str  # the exact supporting span text


class Option(BaseModel):
    optionText: str  # noqa: N815 — mooKIT field name
    isCorrect: bool  # noqa: N815
    misconception: str | None = None  # rationale: which misconception this distractor encodes


class _QuestionBase(BaseModel):
    questionType: QuestionType  # noqa: N815
    questionText: str  # noqa: N815
    bloom_level: BloomLevel = "understand"
    score: float = 1.0
    negativeScore: float = 0.0  # noqa: N815
    citation: Citation
    flags: list[str] = Field(default_factory=list)

    @property
    def is_higher_order(self) -> bool:
        return self.bloom_level in HIGHER_ORDER

    def to_mookit_payload(self) -> dict[str, Any]:  # pragma: no cover - overridden
        raise NotImplementedError


class MCQSingle(_QuestionBase):
    questionType: Literal["mcq_single"] = "mcq_single"  # noqa: N815
    options: list[Option]

    @model_validator(mode="after")
    def _exactly_one_correct(self) -> MCQSingle:
        correct = [o for o in self.options if o.isCorrect]
        if len(self.options) < 2:
            raise ValueError("mcq_single needs at least 2 options")
        if len(correct) != 1:
            raise ValueError(f"mcq_single must have exactly one correct option, got {len(correct)}")
        return self

    def to_mookit_payload(self) -> dict[str, Any]:
        return {
            "questionType": "mcq_single",
            "questionText": self.questionText,
            "score": self.score,
            "negativeScore": self.negativeScore,
            "options": [{"optionText": o.optionText, "isCorrect": int(o.isCorrect)} for o in self.options],
        }


class MCQMulti(_QuestionBase):
    questionType: Literal["mcq_multi"] = "mcq_multi"  # noqa: N815
    options: list[Option]
    allowPartialMarks: bool = False  # noqa: N815

    @model_validator(mode="after")
    def _at_least_one_correct(self) -> MCQMulti:
        if len(self.options) < 2:
            raise ValueError("mcq_multi needs at least 2 options")
        if not any(o.isCorrect for o in self.options):
            raise ValueError("mcq_multi must have at least one correct option")
        return self

    def to_mookit_payload(self) -> dict[str, Any]:
        return {
            "questionType": "mcq_multi",
            "questionText": self.questionText,
            "score": self.score,
            "negativeScore": self.negativeScore,
            "allowPartialMarks": int(self.allowPartialMarks),
            "options": [{"optionText": o.optionText, "isCorrect": int(o.isCorrect)} for o in self.options],
        }


class TrueFalse(_QuestionBase):
    questionType: Literal["true_false"] = "true_false"  # noqa: N815
    trueFalseAnswer: Literal[0, 1]  # noqa: N815

    def to_mookit_payload(self) -> dict[str, Any]:
        return {
            "questionType": "true_false",
            "questionText": self.questionText,
            "score": self.score,
            "negativeScore": self.negativeScore,
            "trueFalseAnswer": self.trueFalseAnswer,
        }


class BlankAnswer(BaseModel):
    answerText: str  # noqa: N815
    caseSensitive: bool = False  # noqa: N815


class Blank(BaseModel):
    blankIndex: int  # noqa: N815
    placeholderLabel: str  # noqa: N815
    answers: list[BlankAnswer]


class FIB(_QuestionBase):
    questionType: Literal["fib"] = "fib"  # noqa: N815
    # Exactly one of (discrete blanks) or (numeric range) must be provided.
    blanks: list[Blank] | None = None
    fibUseRange: bool = False  # noqa: N815
    fibRangeLower: float | None = None  # noqa: N815
    fibRangeUpper: float | None = None  # noqa: N815

    @model_validator(mode="after")
    def _discrete_xor_range(self) -> FIB:
        has_discrete = bool(self.blanks)
        has_range = self.fibUseRange and self.fibRangeLower is not None and self.fibRangeUpper is not None
        if has_discrete == has_range:
            raise ValueError("fib must use EITHER discrete blanks OR a numeric range, not both/neither")
        if has_range and self.fibRangeLower > self.fibRangeUpper:  # type: ignore[operator]
            raise ValueError("fibRangeLower must be <= fibRangeUpper")
        if has_discrete:
            for b in self.blanks or []:
                if not b.answers:
                    raise ValueError("each blank needs at least one accepted answer")
        return self

    def to_mookit_payload(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "questionType": "fib",
            "questionText": self.questionText,
            "score": self.score,
            "negativeScore": self.negativeScore,
        }
        if self.fibUseRange:
            base.update(
                {"fibUseRange": 1, "fibRangeLower": self.fibRangeLower, "fibRangeUpper": self.fibRangeUpper}
            )
        else:
            base["blanks"] = [
                {
                    "blankIndex": b.blankIndex,
                    "placeholderLabel": b.placeholderLabel,
                    "answers": [
                        {"answerText": a.answerText, "caseSensitive": int(a.caseSensitive)}
                        for a in b.answers
                    ],
                }
                for b in (self.blanks or [])
            ]
        return base


class RubricCriterion(BaseModel):
    name: str
    descriptor: str
    points: float


class Rubric(BaseModel):
    criteria: list[RubricCriterion]
    total: float

    @model_validator(mode="after")
    def _points_sum_to_total(self) -> Rubric:
        s = round(sum(c.points for c in self.criteria), 6)
        if round(self.total, 6) != s:
            raise ValueError(f"rubric points sum {s} != total {self.total}")
        if len(self.criteria) < 2:
            raise ValueError("rubric needs at least 2 criteria")
        return self


class Descriptive(_QuestionBase):
    questionType: Literal["descriptive"] = "descriptive"  # noqa: N815
    rubric: Rubric | None = None  # attached by B2.6 before assembly accepts it

    def to_mookit_payload(self) -> dict[str, Any]:
        return {
            "questionType": "descriptive",
            "questionText": self.questionText,
            "score": self.score,
            "negativeScore": self.negativeScore,
        }


AnyQuestion = MCQSingle | MCQMulti | TrueFalse | FIB | Descriptive

SCHEMA_BY_TYPE: dict[str, type[_QuestionBase]] = {
    "mcq_single": MCQSingle,
    "mcq_multi": MCQMulti,
    "true_false": TrueFalse,
    "fib": FIB,
    "descriptive": Descriptive,
}
