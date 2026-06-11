"""POST /v1/quiz/{draft_id}/edit — deterministic per-question quiz edits.

The chat path can apply edits when the model decides to call ``edit_quiz``, but the demo UI needs a
direct, deterministic route so a button click reliably applies one operation. This endpoint reuses the
SAME ``edit_quiz`` tool the orchestrator exposes (identical validation, versioning, re-verification),
then returns the updated draft so the UI can re-render in place.

Operations (per ``EditQuizArgs``): edit_text | regenerate | replace_similar | change_type | flag |
add | remove | set_difficulty.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..contracts.context import RequestContext
from ..core.context import get_request_context

logger = logging.getLogger(__name__)

router = APIRouter()


class QuizEditBody(BaseModel):
    op: str
    index: int | None = None
    qtype: str | None = None
    delta: int | None = None
    difficulty: str | None = None
    questionText: str | None = None  # noqa: N815 — matches the tool/UI field name
    reason: str | None = None
    instruction: str | None = None


@router.post("/quiz/{draft_id}/edit")
async def edit_quiz_endpoint(
    draft_id: str,
    body: QuizEditBody,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
):
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not available.")

    # Permission parity with the chat-driven tool (which is hidden unless the user has it).
    if not ctx.permissions.has_permission("assessments", "update"):
        raise HTTPException(status_code=403, detail="Missing assessments:update permission.")

    try:
        tool = orchestrator.registry.get("edit_quiz")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="edit_quiz tool unavailable.") from exc

    args: dict = {"draft_id": draft_id, "op": body.op}
    for field in ("index", "qtype", "delta", "difficulty", "questionText", "reason", "instruction"):
        value = getattr(body, field)
        if value is not None:
            args[field] = value

    try:
        result = await tool.run(ctx, args)
    except Exception as exc:  # noqa: BLE001 — surface a clean 400 for bad ops/args
        raise HTTPException(status_code=400, detail=f"edit failed: {exc}") from exc
    if not getattr(result, "ok", True):
        raise HTTPException(status_code=400, detail=getattr(result, "message", "edit failed"))

    art = await request.app.state.artifact_registry.get(ctx, draft_id)
    if art is None:
        raise HTTPException(status_code=404, detail="Draft not found after edit.")

    return {
        "success": True,
        "artifact_id": art.id,
        "version": art.version,
        "title": art.title,
        "payload": art.payload,
        "provenance": art.provenance,
    }
