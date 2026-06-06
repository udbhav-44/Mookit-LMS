"""A deterministic fake QuestionGenerator returning canned, schema-valid questions per type.

The citation is a placeholder; the pipeline overrides it with the server-chosen evidence span.
"""

from __future__ import annotations

from app.gen.quiz.params import QuizParams
from app.gen.quiz.rag import Evidence
from app.gen.quiz.schemas import (
    FIB,
    Blank,
    BlankAnswer,
    Citation,
    Descriptive,
    MCQMulti,
    MCQSingle,
    Option,
    QuestionType,
    TrueFalse,
    _QuestionBase,
)

_PLACEHOLDER = Citation(source_id="placeholder", locator={}, quote="placeholder")


async def fake_generator(
    *, qtype: QuestionType, evidence: list[Evidence], params: QuizParams
) -> _QuestionBase:
    bloom = params.bloom_level
    if qtype == "mcq_single":
        return MCQSingle(
            questionText="Where does photosynthesis occur?",
            bloom_level=bloom,
            citation=_PLACEHOLDER,
            options=[
                Option(optionText="Chloroplast", isCorrect=True),
                Option(optionText="Mitochondrion", isCorrect=False, misconception="confuses energy organelles"),
                Option(optionText="Nucleus", isCorrect=False, misconception="thinks DNA site does energy"),
                Option(optionText="Ribosome", isCorrect=False, misconception="confuses with protein synthesis"),
            ],
        )
    if qtype == "mcq_multi":
        return MCQMulti(
            questionText="Which are products of the light reactions?",
            bloom_level=bloom,
            citation=_PLACEHOLDER,
            options=[
                Option(optionText="ATP", isCorrect=True),
                Option(optionText="NADPH", isCorrect=True),
                Option(optionText="Glucose", isCorrect=False, misconception="confuses with Calvin cycle output"),
                Option(optionText="DNA", isCorrect=False, misconception="unrelated macromolecule"),
            ],
        )
    if qtype == "true_false":
        return TrueFalse(
            questionText="Oxygen is released during the light reactions.",
            bloom_level=bloom,
            citation=_PLACEHOLDER,
            trueFalseAnswer=1,
        )
    if qtype == "fib":
        return FIB(
            questionText="The Calvin cycle occurs in the ____.",
            bloom_level=bloom,
            citation=_PLACEHOLDER,
            blanks=[
                Blank(
                    blankIndex=0,
                    placeholderLabel="location",
                    answers=[BlankAnswer(answerText="stroma")],
                )
            ],
        )
    # descriptive
    return Descriptive(
        questionText="Explain how the light reactions and Calvin cycle are connected.",
        bloom_level=bloom,
        citation=_PLACEHOLDER,
    )
