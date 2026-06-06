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

from typing import Any, Protocol

from app.contracts.types import Artifact, ArtifactRegistry, RequestContext
from app.gen.quiz.distractors import distractor_quality_check
from app.gen.quiz.params import Difficulty, QuizParams
from app.gen.quiz.rag import Evidence, RetrieveFn, citation_for, gather_evidence
from app.gen.quiz.rubric import RubricGenerator, attach_rubric, generate_rubric
from app.gen.quiz.schemas import (
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
    ) -> _QuestionBase: ...


class QuizPipeline:
    def __init__(
        self,
        *,
        retrieve: RetrieveFn,
        generator: QuestionGenerator,
        rubric_generator: RubricGenerator | None = None,
        critique: CritiqueFn | None = None,
    ) -> None:
        self._retrieve = retrieve
        self._generator = generator
        self._rubric_generator = rubric_generator
        self._critique = critique

    async def build_draft(
        self,
        ctx: RequestContext,
        registry: ArtifactRegistry,
        *,
        doc_artifact_id: str,
        title: str,
        params: QuizParams,
        topics: list[str] | None = None,
    ) -> Artifact:
        evidence = await gather_evidence(
            self._retrieve, ctx, doc_artifact_id, topics=topics, k=max(params.count, 4)
        )
        if not evidence:
            # No grounding ⇒ no questions. Never fabricate.
            art = Artifact(
                id="",
                type="assessment_draft",
                title=title,
                status="draft",
                payload={"questions": [], "params": params.model_dump(), "warnings": ["no_source_evidence"]},
                provenance=_provenance(doc_artifact_id),
            )
            art_id = await registry.add(ctx, art)
            return await registry.get(ctx, art_id)  # type: ignore[return-value]

        questions = await self._generate_questions(ctx, doc_artifact_id, evidence, params)
        art = Artifact(
            id="",
            type="assessment_draft",
            title=title,
            status="draft",
            payload={
                "questions": [q.model_dump() for q in questions],
                "params": params.model_dump(),
                "warnings": _draft_warnings(questions),
                "source_artifact_id": doc_artifact_id,
            },
            provenance=_provenance(doc_artifact_id),
        )
        art_id = await registry.add(ctx, art)
        return await registry.get(ctx, art_id)  # type: ignore[return-value]

    async def _generate_questions(
        self,
        ctx: RequestContext,
        doc_artifact_id: str,
        evidence: list[Evidence],
        params: QuizParams,
    ) -> list[_QuestionBase]:
        plan = _expand_mix(params)
        out: list[_QuestionBase] = []
        for i, qtype in enumerate(plan):
            span = evidence[i % len(evidence)]
            q = await self._generator(qtype=qtype, evidence=[span], params=params)
            # Enforce grounding: the citation is the server-chosen span, not model-supplied.
            q = q.model_copy(update={"citation": citation_for(doc_artifact_id, span)})
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
        doc_id = draft.payload.get("source_artifact_id", "")

        kind = op.get("op")
        if kind == "add":
            qtype: QuestionType = op["qtype"]
            delta = int(op.get("delta", 1))
            params = params.apply_delta(qtype=qtype, delta=delta)
            evidence = await gather_evidence(self._retrieve, ctx, doc_id, topics=None, k=max(delta, 4))
            for i in range(max(delta, 0)):
                span = evidence[i % len(evidence)] if evidence else None
                if span is None:
                    break
                q = await self._generator(qtype=qtype, evidence=[span], params=params)
                q = q.model_copy(update={"citation": citation_for(doc_id, span)})
                q = await self._postprocess(q, [span])
                questions.append(q.model_dump())
        elif kind == "remove":
            idx = int(op["index"])
            if 0 <= idx < len(questions):
                questions.pop(idx)
        elif kind == "set_difficulty":
            difficulty: Difficulty = op["difficulty"]
            params = params.with_difficulty(difficulty)
        else:
            raise ValueError(f"unknown edit op: {kind}")

        patch = {
            "payload": {
                "questions": questions,
                "params": params.model_dump(),
                "warnings": _draft_warnings_from_dicts(questions),
                "source_artifact_id": doc_id,
            },
            "provenance": {**draft.provenance, "edited_by_human": True},
        }
        return await registry.update(ctx, draft_id, patch)


def _expand_mix(params: QuizParams) -> list[QuestionType]:
    plan: list[QuestionType] = []
    for qtype, n in params.type_mix.items():
        plan.extend([qtype] * n)
    return plan


def _provenance(doc_artifact_id: str) -> dict[str, Any]:
    return {
        "ai_generated": True,
        "edited_by_human": False,
        "source_ids": [doc_artifact_id],
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
