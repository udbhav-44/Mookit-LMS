"""B3.1 — assessment tools.

  * CreateQuizTool (draft)     — run the P2 pipeline → assessment_draft artifact.
  * EditQuizTool (draft)       — apply a versioned edit (add/remove/set_difficulty).
  * PublishAssessmentTool (publish) — return a ProposedAction with the exact mooKIT payload + faithful
    preview + content_hash. NEVER calls mooKIT.

mooKIT create flow described by the payload: POST /assessments/{type} (status=0) → add questions →
publish via PUT (published.status=1). The tool only describes the payload; the gate executes it.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.contracts.types import (
    ArtifactRegistry,
    ProposedAction,
    RequestContext,
    Tool,
    ToolResult,
)
from app.core.hashing import canonical_hash
from app.gen.quiz.params import QuizParams
from app.gen.quiz.pipeline import QuizPipeline
from app.gen.quiz.schemas import SCHEMA_BY_TYPE
from app.llm.schema import strict_schema
from app.preview.render import build_assessment_preview


class CreateQuizArgs(BaseModel):
    doc_artifact_id: str
    title: str
    count: int = 5
    bloom_level: str = "understand"
    difficulty: str = "medium"


class CreateQuizTool(Tool):
    name = "create_quiz"
    description = "Generate a grounded, cited quiz draft from an uploaded document."
    risk_tier = "draft"
    parameters_schema = strict_schema(CreateQuizArgs)
    required_permission = ("assessments", "create")

    def __init__(self, pipeline: QuizPipeline, registry: ArtifactRegistry) -> None:
        self._pipeline = pipeline
        self._registry = registry

    async def run(self, ctx: RequestContext, args: dict[str, Any]) -> ToolResult:
        parsed = CreateQuizArgs.model_validate(args)
        params = QuizParams(
            bloom_level=parsed.bloom_level,  # type: ignore[arg-type]
            difficulty=parsed.difficulty,  # type: ignore[arg-type]
            count=parsed.count,
            type_mix={"mcq_single": parsed.count},
        )
        draft = await self._pipeline.build_draft(
            ctx, self._registry, doc_artifact_id=parsed.doc_artifact_id, title=parsed.title, params=params
        )
        return ToolResult(
            ok=True,
            artifact_id=draft.id,
            data={"questions": len(draft.payload.get("questions", [])), "warnings": draft.payload.get("warnings", [])},
            message=f"Drafted '{draft.title}' with {len(draft.payload.get('questions', []))} question(s).",
        )


class EditQuizArgs(BaseModel):
    draft_id: str
    op: str  # "add" | "remove" | "set_difficulty"
    qtype: str | None = None
    delta: int | None = None
    index: int | None = None
    difficulty: str | None = None


class EditQuizTool(Tool):
    name = "edit_quiz"
    description = "Edit a quiz draft: add questions, remove a question, or change difficulty."
    risk_tier = "draft"
    parameters_schema = strict_schema(EditQuizArgs)
    required_permission = ("assessments", "update")

    def __init__(self, pipeline: QuizPipeline, registry: ArtifactRegistry) -> None:
        self._pipeline = pipeline
        self._registry = registry

    async def run(self, ctx: RequestContext, args: dict[str, Any]) -> ToolResult:
        parsed = EditQuizArgs.model_validate(args)
        op: dict[str, Any] = {"op": parsed.op}
        if parsed.qtype is not None:
            op["qtype"] = parsed.qtype
        if parsed.delta is not None:
            op["delta"] = parsed.delta
        if parsed.index is not None:
            op["index"] = parsed.index
        if parsed.difficulty is not None:
            op["difficulty"] = parsed.difficulty
        updated = await self._pipeline.apply_edit(ctx, self._registry, parsed.draft_id, op)
        return ToolResult(
            ok=True,
            artifact_id=updated.id,
            data={"version": updated.version, "questions": len(updated.payload.get("questions", []))},
            message=f"Updated draft to v{updated.version}.",
        )


class PublishAssessmentArgs(BaseModel):
    draft_id: str
    assessment_type: str = "quizzes"  # quizzes | exams | assignments


class PublishAssessmentTool(Tool):
    name = "publish_assessment"
    description = "Propose publishing a quiz draft to the course (requires confirmation)."
    risk_tier = "publish"
    parameters_schema = strict_schema(PublishAssessmentArgs)
    required_permission = ("assessments", "publish")

    def __init__(self, registry: ArtifactRegistry) -> None:
        self._registry = registry

    async def run(self, ctx: RequestContext, args: dict[str, Any]) -> ProposedAction:
        parsed = PublishAssessmentArgs.model_validate(args)
        draft = await self._registry.get(ctx, parsed.draft_id)
        if draft is None:
            raise KeyError(parsed.draft_id)

        questions = draft.payload.get("questions", [])
        mookit_questions = [_to_mookit_question(q) for q in questions]
        payload: dict[str, Any] = {
            "assessment": {"title": draft.title, "published": {"status": 1}},
            "questions": mookit_questions,
            "section_id": 0,
            "provenance": draft.provenance,
        }
        preview = build_assessment_preview(title=draft.title, questions=questions)
        return ProposedAction(
            action="publish_assessment",
            target_ref={"assessment_type": parsed.assessment_type, "draft_id": parsed.draft_id},
            payload=payload,
            preview=preview,
            content_hash=canonical_hash(payload),
        )


def _to_mookit_question(q: dict[str, Any]) -> dict[str, Any]:
    """Rebuild a typed question from its stored dict and emit the exact mooKIT payload."""
    schema = SCHEMA_BY_TYPE[q["questionType"]]
    model = schema.model_validate(q)
    body = model.to_mookit_payload()
    # Carry the source citation through to the committed object metadata.
    body["_citation"] = q.get("citation")
    return body
