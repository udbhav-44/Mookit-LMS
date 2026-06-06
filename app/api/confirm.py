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

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..auth.permissions import require_action_permission
from ..contracts.context import RequestContext
from ..core.confirmation import ConfirmationGate
from ..core.context import get_request_context
from ..core.executor import DeterministicExecutor

logger = logging.getLogger(__name__)

router = APIRouter()


class ConfirmBody(BaseModel):
    confirm_token: str


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

    executor = DeterministicExecutor(request.app.state.mookit_client)

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
