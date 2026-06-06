"""
GET /v1/sessions/{session_id}  — session history (A1.7)

Routed with prefix /v1/sessions in main.py.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from ..contracts.context import RequestContext
from ..core.context import get_request_context
from ..store.db import Session as SessionModel

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{session_id}")
async def get_session(
    session_id: str,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
):
    """Return session metadata + message transcript for the authenticated user."""
    async with request.app.state.session_factory() as db:
        # Session must belong to this tenant AND user.
        sess_result = await db.execute(
            select(SessionModel).where(
                SessionModel.id == session_id,
                SessionModel.tenant_key == ctx.tenant_key,
                SessionModel.user_id == ctx.user_id,
            )
        )
        sess = sess_result.scalar_one_or_none()

    if sess is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    # Pull messages from Redis first (recent sessions); fall back to Postgres.
    session_store = getattr(request.app.state, "session_store", None)
    messages = []
    if session_store:
        # Build a minimal ctx scoped to this session_id.
        scoped_ctx = ctx.model_copy(update={"session_id": session_id})
        msgs = await session_store.get_transcript(scoped_ctx, max_tokens=8000)
        messages = [{"role": m.role, "content": m.content} for m in msgs]

    return {
        "id": sess.id,
        "tenantKey": sess.tenant_key,
        "createdAt": sess.created_at.isoformat(),
        "summary": sess.summary,
        "messages": messages,
    }
