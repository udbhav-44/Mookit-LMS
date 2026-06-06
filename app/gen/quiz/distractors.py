"""B2.4 — misconception distractors + quality check.

Distractors should encode SPECIFIC anticipated misconceptions (carried in ``Option.misconception``),
not generic "wrong-but-related" filler. ``distractor_quality_check`` flags implausible / overlapping /
"all|none of the above" filler. Flags are advisory — they never auto-delete.
"""

from __future__ import annotations

from app.gen.quiz.schemas import MCQMulti, MCQSingle

_FILLER_PHRASES = ("all of the above", "none of the above", "both a and b", "a and b")


def distractor_quality_check(question: MCQSingle | MCQMulti) -> list[str]:
    """Return advisory flags for low-quality distractors."""
    flags: list[str] = []
    distractors = [o for o in question.options if not o.isCorrect]

    # 1. Filler options.
    for o in question.options:
        if o.optionText.strip().lower() in _FILLER_PHRASES:
            flags.append(f"filler_option:{o.optionText.strip()}")

    # 2. Overlapping / duplicate option texts.
    seen: set[str] = set()
    for o in question.options:
        norm = " ".join(o.optionText.lower().split())
        if norm in seen:
            flags.append(f"duplicate_option:{o.optionText.strip()}")
        seen.add(norm)

    # 3. Distractors missing a misconception rationale.
    for o in distractors:
        if not (o.misconception and o.misconception.strip()):
            flags.append(f"no_misconception_rationale:{o.optionText.strip()}")

    # 4. Implausible: a distractor identical to or trivially shorter than the correct answer.
    correct = next((o for o in question.options if o.isCorrect), None)
    if correct is not None:
        for o in distractors:
            if o.optionText.strip().lower() == correct.optionText.strip().lower():
                flags.append("distractor_equals_correct")

    return flags
