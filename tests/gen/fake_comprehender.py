"""Deterministic fake Comprehender for the photosynthesis sample doc.

Quotes are copied verbatim from tests/fixtures/sample.pdf.txt so ``ground_blueprint`` keeps every
concept. One intentionally-ungrounded concept is available via ``blueprint_with_ungrounded`` to
exercise the grounding filter.
"""

from __future__ import annotations

from app.gen.quiz.blueprint import BloomCount, Blueprint, ConceptNode, LearningObjective
from app.gen.quiz.params import QuizParams

_CONCEPTS = [
    ConceptNode(
        id="c1",
        name="Photosynthesis overview",
        summary="Green plants convert light energy into chemical energy stored in glucose.",
        prerequisites=[],
        representative_quote=(
            "Photosynthesis is the process by which green plants convert light energy into "
            "chemical energy stored in glucose."
        ),
        suggested_bloom=["remember", "understand"],
        common_misconceptions=["Plants get their mass mainly from soil rather than CO2."],
    ),
    ConceptNode(
        id="c2",
        name="Light-dependent reactions",
        summary="Occur in the thylakoid membranes, produce ATP and NADPH, release oxygen.",
        prerequisites=["c1"],
        representative_quote=(
            "The light-dependent reactions take place in the thylakoid membranes and produce ATP "
            "and NADPH, releasing oxygen as a by-product of splitting water."
        ),
        suggested_bloom=["understand", "analyze"],
        common_misconceptions=["Oxygen released comes from CO2 rather than water."],
    ),
    ConceptNode(
        id="c3",
        name="Calvin cycle",
        summary="Light-independent reactions in the stroma that fix CO2 into glucose.",
        prerequisites=["c2"],
        representative_quote=(
            "The Calvin cycle (light-independent reactions) occurs in the stroma and fixes carbon "
            "dioxide into glucose using the ATP and NADPH from the light reactions."
        ),
        suggested_bloom=["understand", "apply", "analyze"],
        common_misconceptions=["The Calvin cycle needs light directly to run."],
    ),
]

_OBJECTIVES = [
    LearningObjective(
        id="o1",
        statement="Describe the overall purpose of photosynthesis.",
        bloom="understand",
        concept_ids=["c1"],
    ),
    LearningObjective(
        id="o2",
        statement="Explain how the light reactions feed the Calvin cycle.",
        bloom="analyze",
        concept_ids=["c2", "c3"],
    ),
]

_DISTRIBUTION = [
    BloomCount(bloom="remember", count=1),
    BloomCount(bloom="understand", count=2),
    BloomCount(bloom="analyze", count=1),
]


async def fake_comprehender(*, sections: list[str], params: QuizParams) -> Blueprint:
    return Blueprint(
        objectives=list(_OBJECTIVES),
        concepts=list(_CONCEPTS),
        suggested_distribution=list(_DISTRIBUTION),
    )


def blueprint_with_ungrounded() -> Blueprint:
    """A blueprint whose last concept's quote is NOT in the sample doc (for grounding tests)."""
    bogus = ConceptNode(
        id="c9",
        name="Fabricated concept",
        summary="Not present in the source.",
        prerequisites=[],
        representative_quote="Mitochondria are the powerhouse of the chloroplast for ATP export.",
        suggested_bloom=["remember"],
        common_misconceptions=[],
    )
    return Blueprint(
        objectives=[
            *_OBJECTIVES,
            LearningObjective(
                id="o9", statement="Bogus objective.", bloom="remember", concept_ids=["c9"]
            ),
        ],
        concepts=[*_CONCEPTS, bogus],
        suggested_distribution=list(_DISTRIBUTION),
    )
