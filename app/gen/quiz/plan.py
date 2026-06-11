"""Phase 2 — coverage planner.

Turns a grounded Blueprint + QuizParams into an explicit, deterministic list of question *slots* — a
"table of specifications" the way a human assessment designer builds one. This replaces the old
``evidence[i % len]`` round-robin: questions now cover objectives on purpose, span Bloom levels
deliberately, and — for engineering — allocate a share of quantitative/problem-solving items rather
than defaulting to pure theory.

No LLM here: the planner is pure and deterministic so coverage is testable and reproducible. The
generator (next stage) consumes each slot, pulls the concept's evidence spans (possibly several, and
possibly across documents for synthesis slots), and writes the question.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.gen.quiz.blueprint import GroundedBlueprint, GroundedConcept
from app.gen.quiz.params import Difficulty, QuizParams
from app.gen.quiz.schemas import HIGHER_ORDER, BloomLevel, QuestionType

# Question types that can carry a numeric / problem-solving answer well.
_QUANTITATIVE_QTYPES: tuple[QuestionType, ...] = ("fib", "descriptive")
_QUANTITATIVE_KINDS = {"quantitative", "procedural", "design"}


class QuestionSlot(BaseModel):
    objective_id: str | None
    concept_ids: list[str]  # 1+; >1 means a cross-concept (possibly cross-document) synthesis item
    bloom: BloomLevel
    qtype: QuestionType
    difficulty: Difficulty
    quantitative: bool = False  # generator should produce a problem-solving item grounded in formulas


def plan_slots(
    bp: GroundedBlueprint,
    params: QuizParams,
    *,
    quantitative_ratio_override: float | None = None,
) -> list[QuestionSlot]:
    """Allocate ``params.count`` slots across objectives × Bloom × (quantitative|conceptual).

    Coverage first: objectives are visited round-robin so each gets a slot before any doubles up.
    The quantitative share is auto-inferred from the blueprint (``quantitative_ratio``) unless the
    instructor overrides it. Higher-order slots draw in prerequisite concepts to enable synthesis.
    """
    concepts_by_id = {gc.concept.id: gc for gc in bp.concepts}
    if not concepts_by_id:
        return []

    qtype_cycle = _expand_type_mix(params)
    bloom_cycle = _bloom_sequence(bp, params, n=params.count)

    ratio = quantitative_ratio_override if quantitative_ratio_override is not None else bp.quantitative_ratio
    ratio = min(1.0, max(0.0, ratio))
    quant_concept_ids = {gc.concept.id for gc in bp.concepts if gc.concept.kind in _QUANTITATIVE_KINDS}
    target_quant = round(params.count * ratio) if quant_concept_ids else 0

    objective_order = _objective_order(bp)

    slots: list[QuestionSlot] = []
    quant_used = 0
    for i in range(params.count):
        obj_id, primary_concept = _next_target(objective_order, concepts_by_id, i)
        bloom = bloom_cycle[i]
        make_quant = (
            quant_used < target_quant
            and primary_concept is not None
            and primary_concept.concept.id in quant_concept_ids
        )
        # If we still owe quantitative slots but this concept isn't quantitative, prefer one that is.
        if not make_quant and quant_used < target_quant and quant_concept_ids:
            forced = _pick_quant_concept(concepts_by_id, quant_concept_ids, i)
            if forced is not None:
                primary_concept, obj_id = forced, _objective_for(bp, forced.concept.id)
                make_quant = True

        concept_ids = _concept_ids_for_slot(primary_concept, concepts_by_id, bloom)
        qtype = _qtype_for_slot(qtype_cycle[i], make_quant)
        if make_quant:
            quant_used += 1

        slots.append(
            QuestionSlot(
                objective_id=obj_id,
                concept_ids=concept_ids,
                bloom=bloom,
                qtype=qtype,
                difficulty=params.difficulty,
                quantitative=make_quant,
            )
        )
    return slots


# ---------------------------------------------------------------------------
# Helpers (pure)
# ---------------------------------------------------------------------------


def _expand_type_mix(params: QuizParams) -> list[QuestionType]:
    plan: list[QuestionType] = []
    for qtype, n in params.type_mix.items():
        plan.extend([qtype] * n)
    if len(plan) < params.count:  # defensive: pad to count
        plan.extend([plan[-1] if plan else "mcq_single"] * (params.count - len(plan)))
    return plan[: params.count]


def _bloom_sequence(bp: GroundedBlueprint, params: QuizParams, *, n: int) -> list[BloomLevel]:
    """Per-slot Bloom levels.

    An explicit ``bloom_level`` is honored for every slot — that's what the instructor selected. A
    ``mixed`` difficulty is the signal to spread cognitive levels: draw from the blueprint's suggested
    distribution (falling back to objective blooms, then the param)."""
    if params.difficulty != "mixed":
        return [params.bloom_level] * n
    seq: list[BloomLevel] = []
    for bc in bp.suggested_distribution:
        seq.extend([bc.bloom] * max(0, bc.count))
    if not seq:
        seq = [o.bloom for o in bp.objectives] or [params.bloom_level]
    return [seq[i % len(seq)] for i in range(n)]


def _objective_order(bp: GroundedBlueprint) -> list[tuple[str | None, list[str]]]:
    """(objective_id, concept_ids) tuples; falls back to one pseudo-objective per concept."""
    if bp.objectives:
        return [(o.id, list(o.concept_ids)) for o in bp.objectives]
    return [(None, [gc.concept.id]) for gc in bp.concepts]


def _next_target(
    objective_order: list[tuple[str | None, list[str]]],
    concepts_by_id: dict[str, GroundedConcept],
    i: int,
) -> tuple[str | None, GroundedConcept | None]:
    obj_id, concept_ids = objective_order[i % len(objective_order)]
    # Rotate through the objective's concepts so repeated visits test different ones.
    valid = [cid for cid in concept_ids if cid in concepts_by_id]
    if not valid:
        return obj_id, None
    cid = valid[(i // len(objective_order)) % len(valid)]
    return obj_id, concepts_by_id[cid]


def _pick_quant_concept(
    concepts_by_id: dict[str, GroundedConcept], quant_ids: set[str], i: int
) -> GroundedConcept | None:
    ordered = [concepts_by_id[c] for c in concepts_by_id if c in quant_ids]
    return ordered[i % len(ordered)] if ordered else None


def _objective_for(bp: GroundedBlueprint, concept_id: str) -> str | None:
    for o in bp.objectives:
        if concept_id in o.concept_ids:
            return o.id
    return None


def _concept_ids_for_slot(
    primary: GroundedConcept | None,
    concepts_by_id: dict[str, GroundedConcept],
    bloom: BloomLevel,
) -> list[str]:
    if primary is None:
        return []
    ids = [primary.concept.id]
    # Higher-order items synthesize: pull in a grounded prerequisite for a cross-concept question.
    if bloom in HIGHER_ORDER:
        for pre in primary.concept.prerequisites:
            if pre in concepts_by_id and pre not in ids:
                ids.append(pre)
                break
    return ids


def _qtype_for_slot(default: QuestionType, quantitative: bool) -> QuestionType:
    if quantitative and default not in _QUANTITATIVE_QTYPES:
        return "fib"  # numeric answer (range) or discrete blank — recomputable & gradeable
    return default
