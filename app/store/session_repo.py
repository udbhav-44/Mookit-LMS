"""Durable session/message reads + writes (Postgres).

Keeps ``app/api/chat.py`` and ``app/api/sessions.py`` thin and testable. All writes go through the
app's ``session_factory``. Redis stays authoritative for the live context window (the orchestrator
keeps writing it); this layer is the durable record that survives Redis' 24h TTL and a reload, and
powers the chat-history list.

Everything here is dialect-agnostic (no Postgres-only ``ON CONFLICT``) so the same code runs against
Postgres in production and in-memory SQLite in tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, insert, select, update

from ..contracts.context import RequestContext
from .db import Artifact as ArtifactModel
from .db import Message as MessageModel
from .db import Session as SessionModel

_TITLE_MAX = 80


def _now() -> datetime:
    return datetime.now(timezone.utc)


def derive_title(first_user_message: str | None) -> str:
    """A compact, human-readable label for the history list."""
    text = " ".join((first_user_message or "").split()).strip()
    if not text:
        return "New chat"
    return text[:_TITLE_MAX].rstrip()


async def upsert_session(
    session_factory: Any,
    ctx: RequestContext,
    *,
    first_user_message: str | None = None,
) -> None:
    """Create the session row if absent, else bump ``updated_at``.

    Sets ``title`` from the first user message only while it is still NULL, so later turns never
    clobber the label. Select-then-write (not ``ON CONFLICT``) keeps this portable across dialects;
    the tiny race for a brand-new session is harmless (worst case: title stays NULL until next turn).
    """
    async with session_factory() as db:
        existing = (
            await db.execute(
                select(SessionModel).where(
                    SessionModel.id == ctx.session_id,
                    SessionModel.tenant_key == ctx.tenant_key,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            await db.execute(
                insert(SessionModel).values(
                    id=ctx.session_id,
                    tenant_key=ctx.tenant_key,
                    user_id=ctx.user_id,
                    title=derive_title(first_user_message) if first_user_message else None,
                    created_at=_now(),
                    updated_at=_now(),
                )
            )
        else:
            values: dict[str, Any] = {"updated_at": _now()}
            if existing.title is None and first_user_message:
                values["title"] = derive_title(first_user_message)
            await db.execute(
                update(SessionModel)
                .where(
                    SessionModel.id == ctx.session_id,
                    SessionModel.tenant_key == ctx.tenant_key,
                )
                .values(**values)
            )
        await db.commit()


async def persist_summary(
    session_factory: Any,
    ctx: RequestContext,
    summary: str | None,
) -> None:
    """Mirror the rolling compaction summary into Postgres so it survives Redis' TTL.

    No-op on empty input. Does not touch ``updated_at`` (the chat turn already bumps it) so a summary
    write can't reorder the history list.
    """
    if not summary:
        return
    async with session_factory() as db:
        await db.execute(
            update(SessionModel)
            .where(
                SessionModel.id == ctx.session_id,
                SessionModel.tenant_key == ctx.tenant_key,
            )
            # Setting updated_at to itself keeps it in the SET clause, which suppresses the column's
            # onupdate default — so a summary write never reorders the most-recent-first history list.
            .values(summary=summary, updated_at=SessionModel.updated_at)
        )
        await db.commit()


async def get_session_summary(
    session_factory: Any,
    ctx: RequestContext,
    session_id: str,
) -> str | None:
    """Durable compaction summary for a session (used to rehydrate Redis on a cold session)."""
    async with session_factory() as db:
        return (
            await db.execute(
                select(SessionModel.summary).where(
                    SessionModel.id == session_id,
                    SessionModel.tenant_key == ctx.tenant_key,
                )
            )
        ).scalar_one_or_none()


async def persist_message(
    session_factory: Any,
    ctx: RequestContext,
    role: str,
    content: str,
    meta: dict | None = None,
) -> None:
    """Append a durable transcript row. No-op on empty content."""
    if not content:
        return
    async with session_factory() as db:
        await db.execute(
            insert(MessageModel).values(
                tenant_key=ctx.tenant_key,
                session_id=ctx.session_id,
                role=role,
                content=content,
                meta=meta,
                created_at=_now(),
            )
        )
        await db.commit()


async def list_sessions(
    session_factory: Any,
    ctx: RequestContext,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Chat-history list for the authenticated user, most-recently-updated first.

    Includes message + artifact counts so the UI can render the list without N extra calls.
    """
    async with session_factory() as db:
        rows = (
            (
                await db.execute(
                    select(SessionModel)
                    .where(
                        SessionModel.tenant_key == ctx.tenant_key,
                        SessionModel.user_id == ctx.user_id,
                    )
                    .order_by(SessionModel.updated_at.desc(), SessionModel.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        ids = [r.id for r in rows]
        msg_counts = await _counts(db, MessageModel, MessageModel.session_id, ctx.tenant_key, ids)
        art_counts = await _counts(db, ArtifactModel, ArtifactModel.session_id, ctx.tenant_key, ids)

    return [
        {
            "id": r.id,
            "title": r.title or "New chat",
            "summary": r.summary,
            "createdAt": r.created_at.isoformat() if r.created_at else None,
            "updatedAt": r.updated_at.isoformat() if r.updated_at else None,
            "messageCount": msg_counts.get(r.id, 0),
            "artifactCount": art_counts.get(r.id, 0),
        }
        for r in rows
    ]


async def _counts(db: Any, model: Any, col: Any, tenant_key: str, ids: list[str]) -> dict[str, int]:
    if not ids:
        return {}
    result = await db.execute(
        select(col, func.count())
        .where(model.tenant_key == tenant_key, col.in_(ids))
        .group_by(col)
    )
    return {row[0]: row[1] for row in result.all()}


async def list_session_messages(
    session_factory: Any,
    ctx: RequestContext,
    session_id: str,
) -> list[dict[str, Any]]:
    """Durable transcript for one session (the Postgres fallback when Redis is cold)."""
    async with session_factory() as db:
        rows = (
            (
                await db.execute(
                    select(MessageModel)
                    .where(
                        MessageModel.tenant_key == ctx.tenant_key,
                        MessageModel.session_id == session_id,
                    )
                    .order_by(MessageModel.created_at.asc(), MessageModel.id.asc())
                )
            )
            .scalars()
            .all()
        )
    return [{"role": r.role, "content": r.content} for r in rows]


async def list_session_artifacts(
    session_factory: Any,
    ctx: RequestContext,
    session_id: str,
) -> dict[str, list[dict[str, Any]]]:
    """Per-chat context: uploads + drafts created in this session, split for the right-hand panel."""
    async with session_factory() as db:
        rows = (
            (
                await db.execute(
                    select(ArtifactModel)
                    .where(
                        ArtifactModel.tenant_key == ctx.tenant_key,
                        ArtifactModel.user_id == ctx.user_id,
                        ArtifactModel.session_id == session_id,
                    )
                    .order_by(ArtifactModel.updated_at.desc())
                )
            )
            .scalars()
            .all()
        )

    uploads: list[dict[str, Any]] = []
    drafts: list[dict[str, Any]] = []
    for r in rows:
        entry = {
            "id": r.id,
            "type": r.type,
            "title": r.title,
            "status": r.status,
            "version": r.version,
            "updatedAt": r.updated_at.isoformat() if r.updated_at else None,
        }
        if r.type == "uploaded_file":
            entry["kind"] = (r.payload or {}).get("kind", "document")
            uploads.append(entry)
        elif r.type.endswith("_draft"):
            drafts.append(entry)
    return {"uploads": uploads, "drafts": drafts}
