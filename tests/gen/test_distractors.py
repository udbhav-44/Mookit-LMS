"""B2.4 acceptance — quality check flags filler / overlap / missing rationale."""

from app.gen.quiz.distractors import distractor_quality_check
from app.gen.quiz.schemas import Citation, MCQSingle, Option

CIT = Citation(source_id="d", locator={}, quote="x")


def test_clean_question_with_rationales_no_flags() -> None:
    q = MCQSingle(
        questionText="q",
        citation=CIT,
        options=[
            Option(optionText="Right", isCorrect=True),
            Option(optionText="Wrong1", isCorrect=False, misconception="m1"),
            Option(optionText="Wrong2", isCorrect=False, misconception="m2"),
        ],
    )
    assert distractor_quality_check(q) == []


def test_flags_all_of_the_above() -> None:
    q = MCQSingle(
        questionText="q",
        citation=CIT,
        options=[
            Option(optionText="Right", isCorrect=True),
            Option(optionText="Wrong", isCorrect=False, misconception="m"),
            Option(optionText="All of the above", isCorrect=False, misconception="m"),
        ],
    )
    flags = distractor_quality_check(q)
    assert any(f.startswith("filler_option") for f in flags)


def test_flags_duplicate_options() -> None:
    q = MCQSingle(
        questionText="q",
        citation=CIT,
        options=[
            Option(optionText="Right", isCorrect=True),
            Option(optionText="Same", isCorrect=False, misconception="m"),
            Option(optionText="same", isCorrect=False, misconception="m"),
        ],
    )
    assert any(f.startswith("duplicate_option") for f in distractor_quality_check(q))


def test_flags_missing_misconception() -> None:
    q = MCQSingle(
        questionText="q",
        citation=CIT,
        options=[
            Option(optionText="Right", isCorrect=True),
            Option(optionText="Wrong", isCorrect=False),
        ],
    )
    assert any(f.startswith("no_misconception_rationale") for f in distractor_quality_check(q))
