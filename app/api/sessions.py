"""
Session history endpoints (prefix /v1/sessions, mounted in main.py):

  GET /v1/sessions                  — list this user's chats (most-recent first) for the history pane.
  GET /v1/sessions/{id}             — session metadata + transcript (Redis-hot, Postgres-cold fallback).
  GET /v1/sessions/{id}/artifacts   — per-chat uploads + drafts for the "this chat" context panel.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select

from ..contracts.context import RequestContext
from ..core.context import get_request_context
from ..store.db import Session as SessionModel
from ..store.session_repo import (
    list_session_artifacts,
    list_session_messages,
    list_sessions,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
async def list_user_sessions(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List the authenticated user's chats (tenant + user scoped), most-recently-updated first."""
    sessions = await list_sessions(request.app.state.session_factory, ctx, limit=limit, offset=offset)
    return {"sessions": sessions}


@router.get("/{session_id}")
async def get_session(
    session_id: str,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
):
    """Return session metadata + message transcript for the authenticated user.

    Transcript comes from Redis when the session is still hot; when Redis has expired (cold session)
    we fall back to the durable Postgres transcript so reopening an old chat still restores it.
    """
    async with request.app.state.session_factory() as db:
        # Session must belong to this tenant AND user.
        sess = (
            await db.execute(
                select(SessionModel).where(
                    SessionModel.id == session_id,
                    SessionModel.tenant_key == ctx.tenant_key,
                    SessionModel.user_id == ctx.user_id,
                )
            )
        ).scalar_one_or_none()

    if sess is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    # Pull messages from Redis first (recent sessions); fall back to durable Postgres.
    session_store = getattr(request.app.state, "session_store", None)
    messages: list[dict] = []
    if session_store:
        scoped_ctx = ctx.model_copy(update={"session_id": session_id})
        msgs = await session_store.get_transcript(scoped_ctx, max_tokens=8000)
        messages = [{"role": m.role, "content": m.content} for m in msgs]
    if not messages:
        messages = await list_session_messages(request.app.state.session_factory, ctx, session_id)

    return {
        "id": sess.id,
        "tenantKey": sess.tenant_key,
        "title": sess.title or "New chat",
        "createdAt": sess.created_at.isoformat() if sess.created_at else None,
        "updatedAt": sess.updated_at.isoformat() if getattr(sess, "updated_at", None) else None,
        "summary": sess.summary,
        "messages": messages,
    }


@router.get("/{session_id}/artifacts")
async def get_session_artifacts(
    session_id: str,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
):
    """Uploads + drafts created in this chat, for the per-chat context panel."""
    async with request.app.state.session_factory() as db:
        sess = (
            await db.execute(
                select(SessionModel).where(
                    SessionModel.id == session_id,
                    SessionModel.tenant_key == ctx.tenant_key,
                    SessionModel.user_id == ctx.user_id,
                )
            )
        ).scalar_one_or_none()
    if sess is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    return await list_session_artifacts(request.app.state.session_factory, ctx, session_id)
