"""B2.3 acceptance — per-type validation + mooKIT field parity."""

import pytest
from pydantic import ValidationError

from app.gen.quiz.schemas import (
    FIB,
    Blank,
    BlankAnswer,
    Citation,
    Descriptive,
    MCQMulti,
    MCQSingle,
    Option,
    Rubric,
    RubricCriterion,
    TrueFalse,
)

CIT = Citation(source_id="d", locator={"page": 1}, quote="x")


def _opts(correct_flags):
    return [Option(optionText=f"opt{i}", isCorrect=c) for i, c in enumerate(correct_flags)]


def test_mcq_single_valid() -> None:
    q = MCQSingle(questionText="q", citation=CIT, options=_opts([True, False, False]))
    payload = q.to_mookit_payload()
    assert payload["questionType"] == "mcq_single"
    assert sum(o["isCorrect"] for o in payload["options"]) == 1


def test_mcq_single_rejects_two_correct() -> None:
    with pytest.raises(ValidationError):
        MCQSingle(questionText="q", citation=CIT, options=_opts([True, True, False]))


def test_mcq_single_rejects_zero_correct() -> None:
    with pytest.raises(ValidationError):
        MCQSingle(questionText="q", citation=CIT, options=_opts([False, False]))


def test_mcq_multi_valid_and_rejects_none_correct() -> None:
    MCQMulti(questionText="q", citation=CIT, options=_opts([True, True, False]))
    with pytest.raises(ValidationError):
        MCQMulti(questionText="q", citation=CIT, options=_opts([False, False]))


def test_true_false_payload() -> None:
    q = TrueFalse(questionText="q", citation=CIT, trueFalseAnswer=1)
    assert q.to_mookit_payload()["trueFalseAnswer"] == 1


def test_fib_discrete_valid() -> None:
    q = FIB(
        questionText="q",
        citation=CIT,
        blanks=[Blank(blankIndex=0, placeholderLabel="x", answers=[BlankAnswer(answerText="stroma")])],
    )
    payload = q.to_mookit_payload()
    assert "blanks" in payload and payload["blanks"][0]["answers"][0]["answerText"] == "stroma"


def test_fib_range_valid() -> None:
    q = FIB(questionText="q", citation=CIT, fibUseRange=True, fibRangeLower=1.0, fibRangeUpper=2.0)
    payload = q.to_mookit_payload()
    assert payload["fibUseRange"] == 1 and payload["fibRangeLower"] == 1.0


def test_fib_rejects_both_forms() -> None:
    with pytest.raises(ValidationError):
        FIB(
            questionText="q",
            citation=CIT,
            blanks=[Blank(blankIndex=0, placeholderLabel="x", answers=[BlankAnswer(answerText="a")])],
            fibUseRange=True,
            fibRangeLower=1.0,
            fibRangeUpper=2.0,
        )


def test_fib_rejects_neither_form() -> None:
    with pytest.raises(ValidationError):
        FIB(questionText="q", citation=CIT)


def test_fib_rejects_inverted_range() -> None:
    with pytest.raises(ValidationError):
        FIB(questionText="q", citation=CIT, fibUseRange=True, fibRangeLower=5.0, fibRangeUpper=1.0)


def test_descriptive_payload() -> None:
    q = Descriptive(questionText="explain", citation=CIT)
    assert q.to_mookit_payload()["questionType"] == "descriptive"


def test_rubric_points_must_sum_to_total() -> None:
    Rubric(
        criteria=[
            RubricCriterion(name="a", descriptor="d", points=0.6),
            RubricCriterion(name="b", descriptor="d", points=0.4),
        ],
        total=1.0,
    )
    with pytest.raises(ValidationError):
        Rubric(
            criteria=[
                RubricCriterion(name="a", descriptor="d", points=0.6),
                RubricCriterion(name="b", descriptor="d", points=0.6),
            ],
            total=1.0,
        )


def test_higher_order_flag() -> None:
    q = MCQSingle(
        questionText="q", citation=CIT, bloom_level="analyze", options=_opts([True, False])
    )
    assert q.is_higher_order is True
