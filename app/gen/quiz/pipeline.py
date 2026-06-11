"""B2.8 — assemble the quiz pipeline into an assessment_draft artifact.

Pipeline per question:
    pick evidence span → generate (per-type schema) → OVERRIDE citation with the chosen span
    (grounding is enforced server-side, not trusted from the model) → distractor quality check (mcq)
    → attach rubric (descriptive) → verify (flags) → collect.

Conversational edits (add/remove/regenerate/change-difficulty) are versioned operations on the
registry artifact — never appended as prose.

All LLM touchpoints are injected seams (QuestionGenerator / RubricGenerator / CritiqueFn) so the whole
pipeline runs deterministically offline against fakes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from app.contracts import Artifact, ArtifactRegistry, RequestContext
from app.gen.quiz.blueprint import (
    Blueprint,
    Comprehender,
    GroundedBlueprint,
    GroundedConcept,
    ground_blueprint_multi,
)
from app.gen.quiz.distractors import distractor_quality_check
from app.gen.quiz.numeric import verify_numeric
from app.gen.quiz.params import Difficulty, QuizParams
from app.gen.quiz.plan import QuestionSlot, plan_slots
from app.gen.quiz.prompting import GenDirectives
from app.gen.quiz.rag import Evidence, RetrieveFn, _normalize_doc_ids, citation_for, gather_evidence
from app.gen.quiz.rubric import RubricGenerator, attach_rubric, generate_rubric
from app.gen.quiz.schemas import (
    FIB,
    SCHEMA_BY_TYPE,
    Descriptive,
    MCQMulti,
    MCQSingle,
    QuestionType,
    _QuestionBase,
)
from app.gen.quiz.verify import CritiqueFn, verify_question


class QuestionGenerator(Protocol):
    async def __call__(
        self,
        *,
        qtype: QuestionType,
        evidence: list[Evidence],
        params: QuizParams,
        directives: GenDirectives | None = None,
    ) -> _QuestionBase: ...


class FetchAllFn(Protocol):
    async def __call__(self, ctx: RequestContext, doc_artifact_id: str) -> list[dict[str, Any]]: ...


class FetchSourceFn(Protocol):
    """Return the original uploaded file bytes for a document (for vision page rendering)."""

    async def __call__(self, ctx: RequestContext, doc_artifact_id: str) -> bytes | None: ...


class VisionComprehenderFn(Protocol):
    async def __call__(self, *, images: list[bytes], params: QuizParams) -> Blueprint: ...


class QuizPipeline:
    def __init__(
        self,
        *,
        retrieve: RetrieveFn,
        generator: QuestionGenerator,
        rubric_generator: RubricGenerator | None = None,
        critique: CritiqueFn | None = None,
        comprehender: Comprehender | None = None,
        fetch_all: FetchAllFn | None = None,
        quantitative_ratio_override: float | None = None,
        vision_comprehender: VisionComprehenderFn | None = None,
        fetch_source: FetchSourceFn | None = None,
        render_pages: Callable[[bytes], list[bytes]] | None = None,
    ) -> None:
        self._retrieve = retrieve
        self._generator = generator
        self._rubric_generator = rubric_generator
        self._critique = critique
        # Blueprint-first path is enabled iff both a comprehender and a full-text accessor are wired.
        self._comprehender = comprehender
        self._fetch_all = fetch_all
        self._quant_override = quantitative_ratio_override
        # Vision comprehension reads rendered page images; grounding still uses the extracted text.
        self._vision_comprehender = vision_comprehender
        self._fetch_source = fetch_source
        self._render_pages = render_pages

    @property
    def _vision_enabled(self) -> bool:
        return (
            self._vision_comprehender is not None
            and self._fetch_source is not None
            and self._render_pages is not None
            and self._fetch_all is not None  # extracted text is still needed for grounding
        )

    @property
    def _blueprint_enabled(self) -> bool:
        return (self._comprehender is not None and self._fetch_all is not None) or self._vision_enabled

    async def build_draft(
        self,
        ctx: RequestContext,
        registry: ArtifactRegistry,
        *,
        doc_artifact_id: str | list[str],
        title: str,
        params: QuizParams,
        topics: list[str] | None = None,
    ) -> Artifact:
        doc_ids = _normalize_doc_ids(doc_artifact_id)
        if self._blueprint_enabled:
            return await self._build_draft_blueprint(ctx, registry, doc_ids, title, params)

        evidence = await gather_evidence(
            self._retrieve, ctx, doc_ids, topics=topics, k=max(params.count, 4)
        )
        if not evidence:
            # No grounding ⇒ no questions. Never fabricate.
            return await self._persist(
                ctx, registry, title=title, question_dicts=[], params=params,
                doc_ids=doc_ids, warnings=["no_source_evidence"],
            )

        questions = await self._generate_questions(ctx, evidence, params)
        return await self._persist(
            ctx, registry, title=title,
            question_dicts=[q.model_dump() for q in questions], params=params,
            doc_ids=doc_ids, warnings=_draft_warnings(questions),
        )

    async def _persist(
        self,
        ctx: RequestContext,
        registry: ArtifactRegistry,
        *,
        title: str,
        question_dicts: list[dict[str, Any]],
        params: QuizParams,
        doc_ids: list[str],
        warnings: list[str],
    ) -> Artifact:
        art = Artifact(
            id="",
            type="assessment_draft",
            title=title,
            status="draft",
            payload={
                "questions": question_dicts,
                "params": params.model_dump(),
                "warnings": warnings,
                "source_artifact_ids": doc_ids,
                "source_artifact_id": doc_ids[0] if doc_ids else "",
            },
            provenance=_provenance(doc_ids),
        )
        art_id = await registry.add(ctx, art)
        return await registry.get(ctx, art_id)  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Blueprint-first path: comprehend → ground → plan → multi-span generate → verify
    # ------------------------------------------------------------------

    async def _build_draft_blueprint(
        self,
        ctx: RequestContext,
        registry: ArtifactRegistry,
        doc_ids: list[str],
        title: str,
        params: QuizParams,
    ) -> Artifact:
        assert self._fetch_all is not None
        # 1. Reconstruct full text per document (multi-PDF supported); needed for grounding either way.
        sources: dict[str, str] = {}
        for doc_id in doc_ids:
            chunks = await self._fetch_all(ctx, doc_id)
            text = "\n\n".join(c.get("text", "") for c in chunks)
            if text.strip():
                sources[doc_id] = text
        if not sources:
            return await self._persist(
                ctx, registry, title=title, question_dicts=[], params=params,
                doc_ids=doc_ids, warnings=["no_source_evidence"],
            )

        # 2. Comprehend (vision if enabled, else text) → blueprint, then ground against the sources.
        grounded = await self._comprehend_and_ground(ctx, doc_ids, sources, params)
        if not grounded.concepts:
            return await self._persist(
                ctx, registry, title=title, question_dicts=[], params=params,
                doc_ids=doc_ids, warnings=["no_grounded_concepts", *grounded.warnings],
            )

        # 3. Plan a deliberate coverage map, then generate one question per slot (multi-span).
        slots = plan_slots(grounded, params, quantitative_ratio_override=self._quant_override)
        grounded_by_id = {gc.concept.id: gc for gc in grounded.concepts}
        questions: list[_QuestionBase] = []
        for slot in slots:
            spans = _slot_evidence(slot, grounded_by_id)
            if not spans:
                continue
            slot_params = params.model_copy(
                update={"bloom_level": slot.bloom, "difficulty": slot.difficulty}
            )
            directives = _slot_directives(slot, grounded_by_id)
            q = await self._generator(
                qtype=slot.qtype, evidence=spans, params=slot_params, directives=directives
            )
            # Enforce grounding server-side: citations are the planner-chosen spans, not model-supplied.
            cites = [citation_for(s.source_doc_id or "", s) for s in spans]
            q = q.model_copy(update={"citation": cites[0], "citations": cites})
            q = await self._postprocess(q, spans)
            # A quantitative slot that didn't return a checkable solution can't be auto-verified.
            if slot.quantitative and not (isinstance(q, FIB) and q.solution is not None):
                q = q.model_copy(update={"flags": sorted({*q.flags, "numeric_missing_solution"})})
            questions.append(q)

        return await self._persist(
            ctx, registry, title=title,
            question_dicts=[q.model_dump() for q in questions], params=params,
            doc_ids=doc_ids, warnings=_draft_warnings(questions) + grounded.warnings,
        )

    async def _comprehend_and_ground(
        self,
        ctx: RequestContext,
        doc_ids: list[str],
        sources: dict[str, str],
        params: QuizParams,
    ) -> GroundedBlueprint:
        """Vision comprehension when enabled (read equations/figures from page images), else text.

        Vision grounds in ``flag`` mode: a formula read from an image but absent from the mangled
        extracted text is KEPT-but-flagged for instructor review rather than dropped."""
        if self._vision_enabled:
            images = await self._render_all_pages(ctx, doc_ids)
            if images:
                assert self._vision_comprehender is not None
                blueprint = await self._vision_comprehender(images=images, params=params)
                return ground_blueprint_multi(blueprint, sources=sources, on_unmatched="flag")
            # No renderable pages (e.g. non-PDF) → fall through to text comprehension if available.

        if self._comprehender is not None:
            sections = [f"[Document {doc_id}]\n{text}" for doc_id, text in sources.items()]
            blueprint = await self._comprehender(sections=sections, params=params)
            return ground_blueprint_multi(blueprint, sources=sources)

        return GroundedBlueprint(warnings=["no_comprehender_available"])

    async def _render_all_pages(self, ctx: RequestContext, doc_ids: list[str]) -> list[bytes]:
        assert self._fetch_source is not None and self._render_pages is not None
        images: list[bytes] = []
        for doc_id in doc_ids:
            data = await self._fetch_source(ctx, doc_id)
            if not data:
                continue
            try:
                images.extend(self._render_pages(data))
            except (ValueError, ImportError):
                # Unrenderable source (not a PDF, or renderer unavailable) → skip; text path covers it.
                continue
        return images

    async def _generate_questions(
        self,
        ctx: RequestContext,
        evidence: list[Evidence],
        params: QuizParams,
    ) -> list[_QuestionBase]:
        plan = _expand_mix(params)
        out: list[_QuestionBase] = []
        for i, qtype in enumerate(plan):
            span = evidence[i % len(evidence)]
            source_doc = span.source_doc_id or ""
            q = await self._generator(qtype=qtype, evidence=[span], params=params)
            # Enforce grounding: the citation is the server-chosen span, not model-supplied.
            q = q.model_copy(update={"citation": citation_for(source_doc, span)})
            q = await self._postprocess(q, [span])
            out.append(q)
        return out

    async def _postprocess(self, q: _QuestionBase, evidence: list[Evidence]) -> _QuestionBase:
        flags: list[str] = []
        if isinstance(q, MCQSingle | MCQMulti):
            flags.extend(distractor_quality_check(q))
        if isinstance(q, Descriptive) and q.rubric is None:
            rubric = await generate_rubric(
                stem=q.questionText,
                evidence=evidence,
                total=q.score,
                generator=self._rubric_generator,
            )
            q = attach_rubric(q, rubric)
        if isinstance(q, FIB) and q.solution is not None:
            flags.extend(_numeric_flags(q.solution))
        report = await verify_question(q, evidence, critique=self._critique)
        merged = sorted(set(q.flags) | set(flags) | set(report.flags))
        return q.model_copy(update={"flags": merged})

    async def apply_edit(
        self,
        ctx: RequestContext,
        registry: ArtifactRegistry,
        draft_id: str,
        op: dict[str, Any],
    ) -> Artifact:
        """Apply a versioned conversational edit. Returns the updated artifact (version bumped)."""
        draft = await registry.get(ctx, draft_id)
        if draft is None:
            raise KeyError(draft_id)
        questions: list[dict[str, Any]] = list(draft.payload.get("questions", []))
        params = QuizParams.model_validate(draft.payload.get("params", {}))
        doc_ids = draft.payload.get("source_artifact_ids") or (
            [draft.payload["source_artifact_id"]]
            if draft.payload.get("source_artifact_id")
            else []
        )

        kind = op.get("op")
        if kind == "add":
            qtype: QuestionType = op["qtype"]
            delta = int(op.get("delta", 1))
            params = params.apply_delta(qtype=qtype, delta=delta)
            evidence = await gather_evidence(
                self._retrieve, ctx, doc_ids, topics=None, k=max(delta, 4)
            )
            for i in range(max(delta, 0)):
                span = evidence[i % len(evidence)] if evidence else None
                if span is None:
                    break
                source_doc = span.source_doc_id or (doc_ids[0] if doc_ids else "")
                q = await self._generator(qtype=qtype, evidence=[span], params=params)
                q = q.model_copy(update={"citation": citation_for(source_doc, span)})
                q = await self._postprocess(q, [span])
                questions.append(q.model_dump())
        elif kind == "remove":
            idx = int(op["index"])
            if 0 <= idx < len(questions):
                questions.pop(idx)
        elif kind == "set_difficulty":
            difficulty: Difficulty = op["difficulty"]
            params = params.with_difficulty(difficulty)
        elif kind == "edit_text":
            # Free-form instructor edit: store as-is, mark human-edited, re-verify to surface breakage.
            questions = await self._edit_text(questions, op)
        elif kind in ("regenerate", "replace_similar"):
            # Re-draft a single question of the SAME type, freshly grounded + re-verified.
            questions = await self._regenerate(ctx, questions, doc_ids, params, op)
        elif kind == "change_type":
            questions, params = await self._change_type(ctx, questions, doc_ids, params, op)
        elif kind == "flag":
            questions = self._flag(questions, op)
        else:
            raise ValueError(f"unknown edit op: {kind}")

        patch = {
            "payload": {
                "questions": questions,
                "params": params.model_dump(),
                "warnings": _draft_warnings_from_dicts(questions),
                "source_artifact_ids": doc_ids,
                "source_artifact_id": doc_ids[0] if doc_ids else "",
            },
            "provenance": {**draft.provenance, "edited_by_human": True},
        }
        return await registry.update(ctx, draft_id, patch)


    # ------------------------------------------------------------------
    # Per-question edit ops (match the affordances the quiz-preview UI dispatches)
    # ------------------------------------------------------------------

    async def _edit_text(
        self, questions: list[dict[str, Any]], op: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Free-form instructor edit. Stored as-is, marked human-edited, re-verified for breakage."""
        idx = int(op["index"])
        if not (0 <= idx < len(questions)):
            return questions
        q = dict(questions[idx])
        if "questionText" in op and op["questionText"] is not None:
            q["questionText"] = str(op["questionText"])
        if op.get("options") is not None:
            q["options"] = op["options"]
        flags = set(q.get("flags", [])) | {"human_edited"}
        flags |= set(await self._reverify_dict(q))
        q["flags"] = sorted(flags)
        questions[idx] = q
        return questions

    async def _regenerate(
        self,
        ctx: RequestContext,
        questions: list[dict[str, Any]],
        doc_ids: list[str],
        params: QuizParams,
        op: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Re-draft one question of the same type, freshly grounded + re-verified."""
        idx = int(op["index"])
        if not (0 <= idx < len(questions)):
            return questions
        qtype: QuestionType = questions[idx]["questionType"]
        offset = 1 if op.get("op") == "replace_similar" else 0
        topics = [op["instruction"]] if op.get("instruction") else None
        new_q = await self._regen_one(ctx, doc_ids, qtype, params, idx + offset, topics)
        if new_q is not None:
            new_q["flags"] = sorted(set(new_q.get("flags", [])) | {"ai_regenerated"})
            questions[idx] = new_q
        return questions

    async def _change_type(
        self,
        ctx: RequestContext,
        questions: list[dict[str, Any]],
        doc_ids: list[str],
        params: QuizParams,
        op: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], QuizParams]:
        """Regenerate one question as a new type; resync params.type_mix to the actual questions."""
        idx = int(op["index"])
        new_type: QuestionType = op["qtype"]
        if not (0 <= idx < len(questions)):
            return questions, params
        new_q = await self._regen_one(ctx, doc_ids, new_type, params, idx, None)
        if new_q is not None:
            new_q["flags"] = sorted(set(new_q.get("flags", [])) | {"ai_regenerated"})
            questions[idx] = new_q
            params = _params_from_questions(questions, base=params)
        return questions, params

    def _flag(self, questions: list[dict[str, Any]], op: dict[str, Any]) -> list[dict[str, Any]]:
        idx = int(op["index"])
        if 0 <= idx < len(questions):
            q = dict(questions[idx])
            reason = str(op.get("reason") or "instructor_flag")
            q["flags"] = sorted(set(q.get("flags", [])) | {reason})
            questions[idx] = q
        return questions

    async def _regen_one(
        self,
        ctx: RequestContext,
        doc_ids: list[str],
        qtype: QuestionType,
        params: QuizParams,
        pick: int,
        topics: list[str] | None,
    ) -> dict[str, Any] | None:
        evidence = await gather_evidence(self._retrieve, ctx, doc_ids, topics=topics, k=max(pick + 2, 4))
        if not evidence:
            return None
        span = evidence[pick % len(evidence)]
        source_doc = span.source_doc_id or (doc_ids[0] if doc_ids else "")
        q = await self._generator(qtype=qtype, evidence=[span], params=params)
        q = q.model_copy(update={"citation": citation_for(source_doc, span)})
        q = await self._postprocess(q, [span])
        return q.model_dump()

    async def _reverify_dict(self, qdict: dict[str, Any]) -> list[str]:
        """Re-run grounding + rule-based checks on an instructor-edited question.

        Returns extra flags; ``edit_invalid`` if the edit broke the question's structural invariants
        (e.g. an MCQ left with no correct option)."""
        qtype = qdict.get("questionType")
        schema = SCHEMA_BY_TYPE.get(qtype) if qtype else None
        if schema is None:
            return ["edit_invalid"]
        try:
            model = schema.model_validate(qdict)
        except Exception:  # noqa: BLE001 — a broken edit shouldn't crash the turn
            return ["edit_invalid"]
        cit = model.citation
        evidence = [Evidence(span_id="", text=cit.quote, locator=cit.locator, source_doc_id=cit.source_id)]
        report = await verify_question(model, evidence, critique=self._critique)
        return report.flags


def _params_from_questions(questions: list[dict[str, Any]], *, base: QuizParams) -> QuizParams:
    """Rebuild a self-consistent QuizParams (type_mix + count) from the actual question list."""
    from collections import Counter

    mix = {k: v for k, v in Counter(q["questionType"] for q in questions).items() if v > 0}
    return base.model_copy(update={"type_mix": mix or {"mcq_single": 0}, "count": len(questions)})


def _slot_directives(
    slot: QuestionSlot, grounded_by_id: dict[str, GroundedConcept]
) -> GenDirectives:
    """Aggregate formulas + misconceptions from a slot's concepts into generation guidance."""
    formulas: list[str] = []
    misconceptions: list[str] = []
    for cid in slot.concept_ids:
        gc = grounded_by_id.get(cid)
        if gc is None:
            continue
        formulas.extend(gc.concept.formulas)
        misconceptions.extend(gc.concept.common_misconceptions)
    return GenDirectives(
        quantitative=slot.quantitative,
        formulas=list(dict.fromkeys(formulas)),  # de-dupe, preserve order
        misconceptions=list(dict.fromkeys(misconceptions)),
    )


def _numeric_flags(solution) -> list[str]:  # noqa: ANN001 — SolutionSpec, avoid import cycle noise
    """Recompute the worked solution and flag if the stated answer doesn't match."""
    result = verify_numeric(
        solution_expr=solution.solution_expr,
        variables={v.name: v.value for v in solution.variables},
        stated_answer=solution.answer,
        expected_unit=solution.unit,
        stated_unit=solution.unit,
    )
    return [] if result.ok else ["numeric_unverified"]


def _slot_evidence(
    slot: QuestionSlot, grounded_by_id: dict[str, GroundedConcept]
) -> list[Evidence]:
    """Build the evidence spans for a slot from its concepts' already-grounded citations."""
    spans: list[Evidence] = []
    for cid in slot.concept_ids:
        gc = grounded_by_id.get(cid)
        if gc is None:
            continue
        spans.append(
            Evidence(
                span_id=cid,
                text=gc.citation.quote,
                locator=gc.citation.locator,
                source_doc_id=gc.citation.source_id,
            )
        )
    return spans


def _expand_mix(params: QuizParams) -> list[QuestionType]:
    plan: list[QuestionType] = []
    for qtype, n in params.type_mix.items():
        plan.extend([qtype] * n)
    return plan


def _provenance(doc_artifact_id: str | list[str]) -> dict[str, Any]:
    ids = _normalize_doc_ids(doc_artifact_id)
    return {
        "ai_generated": True,
        "edited_by_human": False,
        "source_ids": ids,
        "label": "AI-generated · edited by instructor",
    }


def _draft_warnings(questions: list[_QuestionBase]) -> list[str]:
    warnings: list[str] = []
    higher = sum(1 for q in questions if q.is_higher_order)
    if higher:
        warnings.append(f"{higher} higher-order Bloom question(s) — review carefully")
    flagged = sum(1 for q in questions if q.flags)
    if flagged:
        warnings.append(f"{flagged} question(s) raised verification flags")
    return warnings


def _draft_warnings_from_dicts(questions: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    higher = sum(1 for q in questions if q.get("bloom_level") in {"analyze", "evaluate", "create"})
    if higher:
        warnings.append(f"{higher} higher-order Bloom question(s) — review carefully")
    flagged = sum(1 for q in questions if q.get("flags"))
    if flagged:
        warnings.append(f"{flagged} question(s) raised verification flags")
    return warnings
