"""B2.5 acceptance — the 4 hallucination flag classes + no auto-approval + higher-order routing."""

from app.gen.quiz.rag import Evidence
from app.gen.quiz.rubric import _default_rubric
from app.gen.quiz.schemas import (
    FIB,
    Citation,
    Descriptive,
    MCQSingle,
    Option,
    TrueFalse,
)
from app.gen.quiz.verify import check_answer_grounded_in_evidence, verify_question

CIT = Citation(source_id="d", locator={}, quote="photosynthesis occurs in the chloroplast")
EVID = [Evidence(span_id="s1", text="Photosynthesis occurs in the chloroplast.", locator={})]


async def test_clean_mcq_passes() -> None:
    q = MCQSingle(
        questionText="q",
        citation=CIT,
        options=[Option(optionText="a", isCorrect=True), Option(optionText="b", isCorrect=False)],
    )
    report = await verify_question(q, EVID)
    assert report.passed is True and report.flags == []


async def test_ungrounded_flagged() -> None:
    q = TrueFalse(questionText="q", citation=Citation(source_id="d", locator={}, quote="  "), trueFalseAnswer=1)
    report = await verify_question(q, EVID)
    assert "ungrounded" in report.flags
    assert report.passed is False


async def test_descriptive_without_rubric_is_insoluble() -> None:
    q = Descriptive(questionText="explain", citation=CIT)
    report = await verify_question(q, EVID)
    assert "insolvability" in report.flags


async def test_descriptive_with_rubric_passes() -> None:
    q = Descriptive(questionText="explain", citation=CIT, rubric=_default_rubric(total=1.0))
    report = await verify_question(q, EVID)
    assert report.passed is True


async def test_fib_inverted_range_is_math_error() -> None:
    # constructed bypassing the model validator to simulate a bad generation reaching verify
    q = FIB.model_construct(
        questionType="fib",
        questionText="q",
        bloom_level="understand",
        score=1.0,
        negativeScore=0.0,
        citation=CIT,
        flags=[],
        blanks=None,
        fibUseRange=True,
        fibRangeLower=5.0,
        fibRangeUpper=1.0,
    )
    report = await verify_question(q, EVID)
    assert "math_error" in report.flags


async def test_higher_order_routed_to_review() -> None:
    q = MCQSingle(
        questionText="q",
        citation=CIT,
        bloom_level="evaluate",
        options=[Option(optionText="a", isCorrect=True), Option(optionText="b", isCorrect=False)],
    )
    report = await verify_question(q, EVID)
    assert "higher_order_review" in report.flags
    assert report.passed is False


async def test_critique_adds_flags_but_never_approves() -> None:
    async def critique(question, evidence):
        return ["factual_error"]

    q = TrueFalse(questionText="q", citation=CIT, trueFalseAnswer=1)
    report = await verify_question(q, EVID, critique=critique)
    assert "factual_error" in report.flags
    assert report.passed is False  # any flag ⇒ requires human review


def test_grounding_heuristic() -> None:
    q = TrueFalse(questionText="q", citation=CIT, trueFalseAnswer=1)
    assert check_answer_grounded_in_evidence(q, EVID) is True
    blank = TrueFalse(questionText="q", citation=Citation(source_id="d", locator={}, quote=""), trueFalseAnswer=1)
    assert check_answer_grounded_in_evidence(blank, EVID) is False
