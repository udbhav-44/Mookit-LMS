"""Phase 2 — coverage planner: deliberate objective/Bloom/quantitative allocation."""

from app.gen.quiz.blueprint import (
    BloomCount,
    ConceptNode,
    GroundedBlueprint,
    GroundedConcept,
)
from app.gen.quiz.params import QuizParams
from app.gen.quiz.plan import plan_slots
from app.gen.quiz.schemas import Citation


def _gc(cid: str, *, kind: str = "conceptual", prerequisites: list[str] | None = None) -> GroundedConcept:
    return GroundedConcept(
        concept=ConceptNode(
            id=cid,
            name=f"Concept {cid}",
            summary="s",
            kind=kind,  # type: ignore[arg-type]
            prerequisites=prerequisites or [],
            representative_quote="q",
        ),
        citation=Citation(source_id="doc-1", locator={"doc_id": "doc-1"}, quote="q"),
    )


def _blueprint(*, quantitative_ratio: float = 0.0) -> GroundedBlueprint:
    from app.gen.quiz.blueprint import LearningObjective

    return GroundedBlueprint(
        objectives=[
            LearningObjective(id="o1", statement="A", bloom="understand", concept_ids=["c1"]),
            LearningObjective(id="o2", statement="B", bloom="analyze", concept_ids=["c2", "c3"]),
        ],
        concepts=[
            _gc("c1"),
            _gc("c2", kind="quantitative"),
            _gc("c3", prerequisites=["c2"]),
        ],
        suggested_distribution=[BloomCount(bloom="understand", count=2), BloomCount(bloom="analyze", count=1)],
        quantitative_ratio=quantitative_ratio,
    )


def test_slot_count_matches_params() -> None:
    bp = _blueprint()
    slots = plan_slots(bp, QuizParams(count=6, type_mix={"mcq_single": 6}))
    assert len(slots) == 6


def test_every_objective_is_covered() -> None:
    bp = _blueprint()
    slots = plan_slots(bp, QuizParams(count=4, type_mix={"mcq_single": 4}))
    covered = {s.objective_id for s in slots}
    assert "o1" in covered and "o2" in covered


def test_quantitative_ratio_auto_inferred() -> None:
    bp = _blueprint(quantitative_ratio=0.5)
    slots = plan_slots(bp, QuizParams(count=4, type_mix={"mcq_single": 4}))
    quant = [s for s in slots if s.quantitative]
    assert len(quant) == 2  # round(4 * 0.5)
    # Quantitative slots are steered to a numeric-capable type, not left as mcq_single.
    assert all(s.qtype in ("fib", "descriptive") for s in quant)
    assert all("c2" in s.concept_ids for s in quant)  # the only quantitative concept


def test_override_beats_blueprint_ratio() -> None:
    bp = _blueprint(quantitative_ratio=0.9)
    slots = plan_slots(bp, QuizParams(count=4, type_mix={"mcq_single": 4}), quantitative_ratio_override=0.0)
    assert not any(s.quantitative for s in slots)


def test_no_quant_concepts_means_no_quant_slots() -> None:
    from app.gen.quiz.blueprint import LearningObjective

    bp = GroundedBlueprint(
        objectives=[LearningObjective(id="o1", statement="A", bloom="understand", concept_ids=["c1"])],
        concepts=[_gc("c1")],  # all conceptual
        quantitative_ratio=0.8,
    )
    slots = plan_slots(bp, QuizParams(count=3, type_mix={"mcq_single": 3}))
    assert not any(s.quantitative for s in slots)


def test_higher_order_slot_pulls_in_prerequisite() -> None:
    bp = _blueprint()
    # Force analyze bloom; objective o2's c3 has prerequisite c2 → a synthesis slot spanning both.
    slots = plan_slots(bp, QuizParams(count=4, bloom_level="analyze", type_mix={"mcq_single": 4}))
    synth = [s for s in slots if len(s.concept_ids) > 1]
    assert synth, "expected at least one cross-concept synthesis slot"
    assert any(set(s.concept_ids) >= {"c2", "c3"} for s in synth)


def test_empty_blueprint_yields_no_slots() -> None:
    assert plan_slots(GroundedBlueprint(), QuizParams()) == []
