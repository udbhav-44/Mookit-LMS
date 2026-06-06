"""B2.7 — generation knobs (conversationally adjustable)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.gen.quiz.schemas import BloomLevel, QuestionType

Difficulty = Literal["easy", "medium", "hard", "mixed"]
ReadingLevel = Literal["middle_school", "high_school", "undergraduate", "graduate"]


def _default_mix() -> dict[QuestionType, int]:
    return {"mcq_single": 5}


class QuizParams(BaseModel):
    bloom_level: BloomLevel = "understand"
    difficulty: Difficulty = "medium"
    reading_level: ReadingLevel = "undergraduate"
    count: int = Field(default=5, ge=1, le=100)
    # How many of each type to produce; must sum to count.
    type_mix: dict[QuestionType, int] = Field(default_factory=_default_mix)

    @model_validator(mode="after")
    def _mix_sums_to_count(self) -> QuizParams:
        total = sum(self.type_mix.values())
        if total != self.count:
            raise ValueError(f"type_mix sums to {total} but count is {self.count}")
        if any(v < 0 for v in self.type_mix.values()):
            raise ValueError("type_mix counts must be non-negative")
        return self

    def apply_delta(self, *, qtype: QuestionType, delta: int) -> QuizParams:
        """Return a new params with ``delta`` more (or fewer) of ``qtype`` and count updated."""
        mix = dict(self.type_mix)
        mix[qtype] = max(0, mix.get(qtype, 0) + delta)
        mix = {k: v for k, v in mix.items() if v > 0}
        return self.model_copy(update={"type_mix": mix, "count": sum(mix.values())})

    def with_difficulty(self, difficulty: Difficulty) -> QuizParams:
        return self.model_copy(update={"difficulty": difficulty})
