"""B3.1 — assessment tools.

  * CreateQuizTool (draft)     — run the P2 pipeline → assessment_draft artifact.
  * EditQuizTool (draft)       — apply a versioned edit (add/remove/set_difficulty).
  * PublishAssessmentTool (publish) — return a ProposedAction with the exact mooKIT payload + faithful
    preview + content_hash. NEVER calls mooKIT.

mooKIT create flow described by the payload: POST /assessments/{type} (status=0) → add questions →
publish via PUT (published.status=1). The tool only describes the payload; the gate executes it.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel

from app.contracts import (
    ArtifactRegistry,
    ProposedAction,
    RequestContext,
    Tool,
    ToolResult,
)
from app.contracts.errors import ErrorInfo
from app.core.hashing import canonical_hash
from app.gen.quiz.params import QuizParams
from app.gen.quiz.pipeline import QuizPipeline
from app.gen.quiz.schemas import SCHEMA_BY_TYPE
from app.llm.schema import strict_schema
from app.preview.render import build_assessment_preview

_DAY = 86400


def _default_assessment_create(title: str) -> dict[str, Any]:
    """An AssessmentCreate-compatible body with sensible default dates (draft status=0)."""
    now = int(time.time())
    return {
        "title": title,
        "startDate": now,
        "endDate": now + 7 * _DAY,
        "endDapDate": now + 7 * _DAY,
        "resultsDate": now + 8 * _DAY,
        "published": {"status": 0, "releaseOn": None},
        "timed": 0,
        "retakeAllowed": 0,
        "showCorrectAnswers": 0,
        "misconductDetection": 0,
        "minimumOofTimeMs": 5000,
        "secureExamBrowser": 0,
        "calculatorEnabled": 0,
        "restrictSingleIp": 0,
    }


class CreateQuizArgs(BaseModel):
    doc_artifact_id: str | None = None
    doc_artifact_ids: list[str] = []
    title: str
    # "generate" = author fresh grounded questions (requires a known count).
    # "replicate" = reproduce an uploaded question paper VERBATIM (count comes from the paper).
    mode: Literal["generate", "replicate"] = "generate"
    # Number of questions to generate. REQUIRED for mode="generate"; ignored for "replicate".
    # Never assume a default — determine it from the instructor's request, or ask via ask_user.
    count: int | None = None
    bloom_level: str = "understand"
    difficulty: str = "medium"


class CreateQuizTool(Tool):
    name = "create_quiz"
    description = (
        "Create a quiz draft from one or more uploaded documents. mode='generate' authors fresh "
        "grounded questions and REQUIRES a 'count' you derived from the instructor's request (do "
        "not guess — use ask_user if unknown). mode='replicate' reproduces an uploaded question "
        "paper verbatim, using however many questions the paper contains. Pass a single "
        "doc_artifact_id OR a list in doc_artifact_ids."
    )
    risk_tier = "draft"
    parameters_schema = strict_schema(CreateQuizArgs)
    required_permission = ("assessments", "create")

    def __init__(self, pipeline: QuizPipeline, registry: ArtifactRegistry) -> None:
        self._pipeline = pipeline
        self._registry = registry

    async def run(self, ctx: RequestContext, args: dict[str, Any]) -> ToolResult:
        parsed = CreateQuizArgs.model_validate(args)
        doc_ids = parsed.doc_artifact_ids or (
            [parsed.doc_artifact_id] if parsed.doc_artifact_id else []
        )
        if not doc_ids:
            return ToolResult(
                ok=False,
                message="No source document(s) specified.",
                error=ErrorInfo(
                    code="missing_doc",
                    message="Provide doc_artifact_id or doc_artifact_ids.",
                ),
            )

        if parsed.mode == "replicate":
            if not self._pipeline.replicate_enabled:
                return ToolResult(
                    ok=False,
                    message="Verbatim replication isn't available for this source.",
                    error=ErrorInfo(
                        code="replicate_unavailable",
                        message=(
                            "The source can't be rendered for verbatim transcription. Ask the "
                            "instructor how many questions to generate instead (mode='generate')."
                        ),
                    ),
                )
            draft = await self._pipeline.build_replica(
                ctx, self._registry, doc_artifact_id=doc_ids, title=parsed.title
            )
            n = len(draft.payload.get("questions", []))
            return ToolResult(
                ok=True,
                artifact_id=draft.id,
                data={"questions": n, "warnings": draft.payload.get("warnings", []), "mode": "replicate"},
                message=f"Reproduced '{draft.title}' verbatim with {n} question(s) from the uploaded paper.",
            )

        # mode == "generate": the count must be known — never silently default to a fixed number.
        if parsed.count is None or parsed.count < 1:
            return ToolResult(
                ok=False,
                message="Number of questions not specified.",
                error=ErrorInfo(
                    code="count_required",
                    message=(
                        "No question count was given. Determine it from the instructor's request, "
                        "or call ask_user to ask how many questions they want before retrying."
                    ),
                ),
            )
        params = QuizParams(
            bloom_level=parsed.bloom_level,  # type: ignore[arg-type]
            difficulty=parsed.difficulty,  # type: ignore[arg-type]
            count=parsed.count,
            type_mix={"mcq_single": parsed.count},
        )
        draft = await self._pipeline.build_draft(
            ctx, self._registry, doc_artifact_id=doc_ids, title=parsed.title, params=params
        )
        return ToolResult(
            ok=True,
            artifact_id=draft.id,
            data={"questions": len(draft.payload.get("questions", [])), "warnings": draft.payload.get("warnings", [])},
            message=f"Drafted '{draft.title}' with {len(draft.payload.get('questions', []))} question(s).",
        )


class EditQuizArgs(BaseModel):
    draft_id: str
    # Draft-level: add | remove | set_difficulty.
    # Per-question: edit_text | regenerate | replace_similar | change_type | flag.
    op: str
    qtype: str | None = None
    delta: int | None = None
    index: int | None = None
    difficulty: str | None = None
    questionText: str | None = None  # noqa: N815 — edit_text payload
    reason: str | None = None  # flag reason
    instruction: str | None = None  # optional hint to bias regeneration


class EditQuizTool(Tool):
    name = "edit_quiz"
    description = (
        "Edit a quiz draft. Draft-level ops: add, remove, set_difficulty. Per-question ops "
        "(by index): edit_text (instructor text), regenerate / replace_similar (re-draft one "
        "question, re-grounded + re-verified), change_type, flag."
    )
    risk_tier = "draft"
    parameters_schema = strict_schema(EditQuizArgs)
    required_permission = ("assessments", "update")

    def __init__(self, pipeline: QuizPipeline, registry: ArtifactRegistry) -> None:
        self._pipeline = pipeline
        self._registry = registry

    async def run(self, ctx: RequestContext, args: dict[str, Any]) -> ToolResult:
        parsed = EditQuizArgs.model_validate(args)
        op: dict[str, Any] = {"op": parsed.op}
        for field in ("qtype", "delta", "index", "difficulty", "questionText", "reason", "instruction"):
            value = getattr(parsed, field)
            if value is not None:
                op[field] = value
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
        mookit_questions = [_to_question_create(q) for q in questions]
        citations = [q.get("citation") for q in questions]
        # Executor-compatible composite payload: create assessment (status 0) → add questions →
        # publish (status 1). Magic key `_type` selects quizzes|exams|assignments.
        assessment_body = _default_assessment_create(draft.title)
        payload: dict[str, Any] = {
            "_type": parsed.assessment_type,
            "assessment": assessment_body,
            "questions": mookit_questions,
            "citations": citations,        # carried for audit/provenance; not sent to QuestionCreate
            "provenance": draft.provenance,
        }
        preview = build_assessment_preview(
            title=draft.title,
            questions=questions,
            assessment=assessment_body,
            assessment_type=parsed.assessment_type,
        )
        return ProposedAction(
            action="publish_assessment",
            target_ref={"assessment_type": parsed.assessment_type, "draft_id": parsed.draft_id},
            payload=payload,
            preview=preview,
            content_hash=canonical_hash(payload),
        )


def _to_question_create(q: dict[str, Any]) -> dict[str, Any]:
    """Produce a QuestionCreate-compatible dict (mooKIT schema) from a stored question."""
    schema = SCHEMA_BY_TYPE[q["questionType"]]
    model = schema.model_validate(q)
    body = model.to_mookit_payload()
    body["published"] = {"status": 1}
    # mooKIT FibBlankInput.answers is list[str]; flatten our richer blank answers.
    if body.get("questionType") == "fib" and "blanks" in body:
        for blank in body["blanks"]:
            blank["answers"] = [a["answerText"] for a in blank.get("answers", [])]
    return body
