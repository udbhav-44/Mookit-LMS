"""
POST /v1/actions/{action_id}/confirm  — execute a pending confirmed action (A3.2)
POST /v1/actions/{action_id}/reject   — discard a pending action

Security chain enforced on /confirm:
  1. User must be authenticated (get_request_context enforces headers).
  2. Re-validate permissions at execution time — not just at proposal time.
  3. Verify the one-time confirm_token (constant-time compare in ConfirmationGate).
  4. Verify content_hash still matches the stored payload (re-derived server-side).
  5. Only then hand off to DeterministicExecutor.
  6. Mark the token consumed (status=confirmed) so it can never be reused.
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from ..auth.permissions import require_action_permission
from ..contracts.context import RequestContext
from ..core.confirmation import ConfirmationGate
from ..core.context import get_request_context
from ..core.executor import DeterministicExecutor
from ..store.db import PendingAction

logger = logging.getLogger(__name__)

router = APIRouter()


class ConfirmBody(BaseModel):
    confirm_token: str


class ReviseAnnouncementBody(BaseModel):
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    audience: str | int | None = None          # "all" or a section taxonomy id
    audience_label: str | None = None          # cosmetic label for the preview/audit
    notify_mail: int | None = None             # 0=LMS-only, 1=also email
    schedule_at: int | None = None             # unix seconds; future => scheduled, else send now
    file_ids: list[int] = Field(default_factory=list)


class ReviseAssessmentBody(BaseModel):
    assessment_type: Literal["quizzes", "exams", "assignments"]
    start_date: int
    end_date: int
    end_dap_date: int
    results_date: int
    timed: int = 0
    duration: int | None = None
    instructions: str | None = None
    show_correct_answers: int = 0
    retake_allowed: int = 0


@router.post("/actions/{action_id}/confirm")
async def confirm_action(
    action_id: str,
    body: ConfirmBody,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
):
    audit = getattr(request.app.state, "audit_logger", None)

    gate = ConfirmationGate(request.app.state.session_factory)
    valid, action = await gate.verify_and_get(action_id, ctx.tenant_key, body.confirm_token)

    if not valid or action is None:
        # Intentionally vague — don't leak which check failed.
        raise HTTPException(
            status_code=404,
            detail="Action not found, already processed, token invalid, or payload hash mismatch.",
        )

    # Re-validate permissions at execution time (A3.2).
    # This catches revocations that happened between proposal and confirmation.
    require_action_permission(ctx, action.action)

    executor = DeterministicExecutor(
        request.app.state.mookit_client,
        session_factory=request.app.state.session_factory,
        redis=getattr(request.app.state, "redis", None),
    )

    try:
        result = await executor.execute(ctx, action.action, dict(action.payload))
        await gate.complete(action_id, "confirmed")

        if audit:
            await audit.log(ctx, action=f"confirmed:{action.action}", status="success")

        logger.info(
            "Action confirmed: action_id=%s action=%s tenant=%s user=%d",
            action_id, action.action, ctx.tenant_key, ctx.user_id,
        )
        return {"success": True, "data": result}

    except HTTPException:
        raise
    except Exception as exc:
        await gate.complete(action_id, "failed")
        if audit:
            await audit.log(ctx, action=f"confirmed:{action.action}", status="error")
        logger.exception("Executor error for action_id=%s", action_id)
        raise HTTPException(status_code=500, detail=f"Execution failed: {exc}") from exc


@router.post("/actions/{action_id}/reject")
async def reject_action(
    action_id: str,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
):
    audit = getattr(request.app.state, "audit_logger", None)

    gate = ConfirmationGate(request.app.state.session_factory)
    # For rejection we only need the action to exist and be owned by this tenant.
    # We do NOT require the confirm_token — the user can always reject their own proposals.
    async with request.app.state.session_factory() as session:
        from sqlalchemy import select

        from ..store.db import PendingAction
        result = await session.execute(
            select(PendingAction).where(
                PendingAction.id == action_id,
                PendingAction.tenant_key == ctx.tenant_key,
                PendingAction.status == "pending",
            )
        )
        action = result.scalar_one_or_none()

    if action is None:
        raise HTTPException(status_code=404, detail="Action not found or already processed.")

    await gate.complete(action_id, "rejected")

    if audit:
        await audit.log(ctx, action=f"rejected:{action.action}", status="success")

    logger.info(
        "Action rejected: action_id=%s action=%s tenant=%s user=%d",
        action_id, action.action, ctx.tenant_key, ctx.user_id,
    )
    return {"success": True, "message": f"Action {action_id} rejected."}


async def _pending_action_type(request: Request, action_id: str, tenant_key: str) -> str | None:
    """Look up the action type of a pending action so /revise can dispatch by kind."""
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(PendingAction.action).where(
                PendingAction.id == action_id,
                PendingAction.tenant_key == tenant_key,
                PendingAction.status == "pending",
            )
        )
        return result.scalar_one_or_none()


@router.post("/actions/{action_id}/revise")
async def revise_action(
    action_id: str,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
):
    """Apply instructor edits to a pending action before confirm.

    Dispatches by the pending action's type:
      * send_announcement  → subject/body (+ audience/email/schedule/attachments)
      * publish_assessment → quiz type, dates, timing, flags

    Updates the stored payload + content_hash + preview so the confirm step still executes exactly
    what the instructor reviewed in the modal.
    """
    action_type = await _pending_action_type(request, action_id, ctx.tenant_key)
    if action_type is None:
        raise HTTPException(status_code=404, detail="Pending action not found.")

    try:
        raw = await request.json()
    except Exception:
        raw = {}

    if action_type == "send_announcement":
        return await _revise_announcement(action_id, raw, request, ctx)
    if action_type == "publish_assessment":
        return await _revise_assessment(action_id, raw, request, ctx)
    raise HTTPException(
        status_code=400, detail=f"Action type '{action_type}' does not support revise."
    )


async def _revise_announcement(action_id: str, raw: dict, request: Request, ctx: RequestContext):
    if not ctx.permissions.has_permission("announcements", "publish"):
        raise HTTPException(status_code=403, detail="Missing announcements:publish permission.")
    try:
        body = ReviseAnnouncementBody.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    # Validate a section-audience choice now so the instructor gets immediate feedback (the executor
    # re-validates fail-closed at confirm time too). "all" needs no lookup.
    aud = body.audience
    is_section = isinstance(aud, int) or (isinstance(aud, str) and aud.strip().isdigit())
    if is_section:
        sid = int(aud)
        mookit = getattr(request.app.state, "mookit_client", None)
        try:
            terms = await mookit.list_taxonomy(ctx, "section") if mookit else []
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail="Couldn't verify the target section.") from exc
        match = next((t for t in terms if t.id == sid), None)
        if match is None:
            available = ", ".join(t.name for t in terms) or "(none)"
            raise HTTPException(
                status_code=400,
                detail=f"Section id {sid} is not a course section. Available: {available}.",
            )
        if not body.audience_label:
            body.audience_label = match.name

    gate = ConfirmationGate(request.app.state.session_factory)
    revised = await gate.revise_announcement(
        action_id, ctx.tenant_key, title=body.title, description=body.description,
        audience=body.audience, audience_label=body.audience_label,
        notify_mail=body.notify_mail, schedule_at=body.schedule_at,
        file_ids=body.file_ids,
    )
    if revised is None:
        raise HTTPException(status_code=404, detail="Pending announcement action not found.")

    draft_id = (revised.target_ref or {}).get("draft_id")
    registry = getattr(request.app.state, "artifact_registry", None)
    if draft_id and registry is not None:
        from ..gen.provenance import mark_edited

        art = await registry.get(ctx, draft_id)
        if art is not None and art.type == "announcement_draft":
            payload = dict(art.payload)
            payload["title"] = body.title.strip()
            payload["description"] = revised.payload.get("description", body.description)
            await registry.update(
                ctx, draft_id,
                {"title": payload["title"], "payload": payload,
                 "provenance": mark_edited(art.provenance)},
            )

    return {
        "success": True,
        "preview": revised.preview_json,
        "content_hash": revised.content_hash,
    }


async def _revise_assessment(action_id: str, raw: dict, request: Request, ctx: RequestContext):
    if not ctx.permissions.has_permission("assessments", "update"):
        raise HTTPException(status_code=403, detail="Missing assessments:update permission.")
    try:
        body = ReviseAssessmentBody.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    gate = ConfirmationGate(request.app.state.session_factory)
    try:
        revised = await gate.revise_assessment(
            action_id, ctx.tenant_key,
            assessment_type=body.assessment_type,
            start_date=body.start_date,
            end_date=body.end_date,
            end_dap_date=body.end_dap_date,
            results_date=body.results_date,
            timed=body.timed,
            duration=body.duration,
            instructions=body.instructions,
            show_correct_answers=body.show_correct_answers,
            retake_allowed=body.retake_allowed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if revised is None:
        raise HTTPException(status_code=404, detail="Pending assessment action not found.")

    return {
        "success": True,
        "preview": revised.preview_json,
        "content_hash": revised.content_hash,
    }
