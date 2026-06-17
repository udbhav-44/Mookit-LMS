"""Durable session history — repo-level tests against in-memory SQLite (no Postgres/Redis).

Validates the logic the /v1/sessions endpoints call: upsert idempotency + title derivation, durable
message round-trip, history-list ordering/counts/isolation, and per-session artifact filtering.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.chat import _REHYDRATE_MAX, _rehydrate_if_cold
from app.contracts.context import PermissionMatrix, RequestContext
from app.store.db import Artifact as ArtifactModel
from app.store.db import Base
from app.store.db import Message as MessageModel
from app.store.db import Session as SessionModel
from app.store.in_memory import InMemorySessionStore
from app.store.session_repo import (
    derive_title,
    get_session_summary,
    list_session_artifacts,
    list_session_messages,
    list_sessions,
    persist_message,
    persist_summary,
    upsert_session,
)

# Only the tables this feature touches — skips DocChunk's pgvector column (unsupported on SQLite).
_TABLES = [SessionModel.__table__, MessageModel.__table__, ArtifactModel.__table__]


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TABLES))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _ctx(*, tenant="t1:c1", user=1, session="s1") -> RequestContext:
    return RequestContext(
        instance_id="t1", course_id="c1", user_id=user, role="instructor",
        session_id=session, forwarded_headers={"course": "c1", "token": "j", "uid": str(user)},
        permissions=PermissionMatrix(resources={}), tenant_key=tenant, request_id="r1",
    )


async def _seed_session(sf, ctx, *, title, updated_at):
    """Insert a session row directly with a controlled updated_at (for ordering assertions)."""
    async with sf() as db:
        db.add(SessionModel(
            id=ctx.session_id, tenant_key=ctx.tenant_key, user_id=ctx.user_id,
            title=title, created_at=updated_at, updated_at=updated_at,
        ))
        await db.commit()


def test_derive_title_trims_and_falls_back():
    assert derive_title("  Create a   quiz on photosynthesis  ") == "Create a quiz on photosynthesis"
    assert derive_title("") == "New chat"
    assert derive_title(None) == "New chat"
    assert len(derive_title("x" * 200)) == 80


async def test_upsert_is_idempotent_and_sets_title_once(session_factory):
    ctx = _ctx(session="s-upsert")
    await upsert_session(session_factory, ctx, first_user_message="First message wins the title")
    await upsert_session(session_factory, ctx, first_user_message="A different later message")

    async with session_factory() as db:
        rows = (await db.execute(SessionModel.__table__.select())).all()
    assert len(rows) == 1, "upsert must not create duplicate session rows"
    sessions = await list_sessions(session_factory, ctx)
    assert sessions[0]["title"] == "First message wins the title"


async def test_persist_and_list_messages_roundtrip(session_factory):
    ctx = _ctx(session="s-msg")
    await upsert_session(session_factory, ctx, first_user_message="hi")
    await persist_message(session_factory, ctx, "user", "hello")
    await persist_message(session_factory, ctx, "assistant", "hi there")
    await persist_message(session_factory, ctx, "assistant", "")  # empty is a no-op

    msgs = await list_session_messages(session_factory, ctx, ctx.session_id)
    assert msgs == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]


async def test_list_sessions_ordering_counts_and_isolation(session_factory):
    now = datetime.now(timezone.utc)
    u1_old = _ctx(user=1, session="u1-old")
    u1_new = _ctx(user=1, session="u1-new")
    u2 = _ctx(user=2, session="u2-only")
    await _seed_session(session_factory, u1_old, title="Old chat", updated_at=now - timedelta(hours=2))
    await _seed_session(session_factory, u1_new, title="New chat msg", updated_at=now)
    await _seed_session(session_factory, u2, title="Someone else", updated_at=now)

    await persist_message(session_factory, u1_new, "user", "q")
    await persist_message(session_factory, u1_new, "assistant", "a")
    async with session_factory() as db:
        db.add(ArtifactModel(
            id="art-1", tenant_key=u1_new.tenant_key, type="assessment_draft", title="Quiz",
            status="draft", version=1, payload={}, provenance={}, user_id=1,
            session_id=u1_new.session_id,
        ))
        await db.commit()

    listing = await list_sessions(session_factory, _ctx(user=1))
    ids = [s["id"] for s in listing]
    assert ids == ["u1-new", "u1-old"]  # most-recently-updated first
    assert "u2-only" not in ids  # user isolation
    new_row = next(s for s in listing if s["id"] == "u1-new")
    assert new_row["messageCount"] == 2
    assert new_row["artifactCount"] == 1


async def test_list_session_artifacts_splits_and_filters_by_session(session_factory):
    ctx = _ctx(session="s-art")
    async with session_factory() as db:
        db.add_all([
            ArtifactModel(id="f1", tenant_key=ctx.tenant_key, type="uploaded_file", title="paper.pdf",
                          status="uploaded", version=1, payload={"kind": "document"}, provenance={},
                          user_id=1, session_id="s-art"),
            ArtifactModel(id="d1", tenant_key=ctx.tenant_key, type="assessment_draft", title="Quiz",
                          status="draft", version=2, payload={}, provenance={}, user_id=1,
                          session_id="s-art"),
            ArtifactModel(id="other", tenant_key=ctx.tenant_key, type="assessment_draft", title="Nope",
                          status="draft", version=1, payload={}, provenance={}, user_id=1,
                          session_id="different-session"),
        ])
        await db.commit()

    result = await list_session_artifacts(session_factory, ctx, "s-art")
    assert [u["id"] for u in result["uploads"]] == ["f1"]
    assert [d["id"] for d in result["drafts"]] == ["d1"]
    assert result["uploads"][0]["kind"] == "document"


# ── Rehydration: warm the orchestrator's Redis memory from Postgres on a cold session ──────────

async def test_rehydrate_cold_session_restores_durable_transcript(session_factory):
    ctx = _ctx(session="s-cold")
    await upsert_session(session_factory, ctx, first_user_message="earlier turn")
    await persist_message(session_factory, ctx, "user", "earlier turn")
    await persist_message(session_factory, ctx, "assistant", "earlier reply")

    store = InMemorySessionStore()  # simulates Redis having expired (empty)
    assert await store.has_transcript(ctx) is False

    await _rehydrate_if_cold(store, session_factory, ctx)

    restored = await store.get_transcript(ctx, max_tokens=10_000)
    assert [(m.role, m.content) for m in restored] == [
        ("user", "earlier turn"),
        ("assistant", "earlier reply"),
    ]


async def test_rehydrate_noop_when_already_warm(session_factory):
    ctx = _ctx(session="s-warm")
    # Postgres has an old turn, but Redis is already warm with a live one — must not be clobbered.
    await persist_message(session_factory, ctx, "user", "durable-only turn")
    store = InMemorySessionStore()
    await store.append_message(ctx, "user", "live turn")

    await _rehydrate_if_cold(store, session_factory, ctx)

    restored = await store.get_transcript(ctx, max_tokens=10_000)
    assert [m.content for m in restored] == ["live turn"]


async def test_rehydrate_noop_for_brand_new_session(session_factory):
    ctx = _ctx(session="s-brand-new")
    store = InMemorySessionStore()

    await _rehydrate_if_cold(store, session_factory, ctx)

    assert await store.has_transcript(ctx) is False


async def test_rehydrate_caps_to_recent_window(session_factory):
    ctx = _ctx(session="s-long")
    total = _REHYDRATE_MAX + 10
    for i in range(total):
        await persist_message(session_factory, ctx, "user", f"msg {i}")

    store = InMemorySessionStore()
    await _rehydrate_if_cold(store, session_factory, ctx)

    restored = await store.get_transcript(ctx, max_tokens=10_000_000)
    assert len(restored) == _REHYDRATE_MAX
    # Keeps the most-recent window (oldest dropped).
    assert restored[0].content == f"msg {total - _REHYDRATE_MAX}"
    assert restored[-1].content == f"msg {total - 1}"


async def test_persist_and_get_summary_roundtrip(session_factory):
    ctx = _ctx(session="s-sum")
    await upsert_session(session_factory, ctx, first_user_message="hi")
    await persist_summary(session_factory, ctx, "")  # empty is a no-op
    assert await get_session_summary(session_factory, ctx, ctx.session_id) is None

    await persist_summary(session_factory, ctx, "condensed history of the chat")
    assert await get_session_summary(session_factory, ctx, ctx.session_id) == "condensed history of the chat"


async def test_persist_summary_does_not_reorder_history(session_factory):
    """Writing a summary must not bump updated_at (which would reorder the history list)."""
    now = datetime.now(timezone.utc)
    older = _ctx(user=1, session="sum-older")
    newer = _ctx(user=1, session="sum-newer")
    await _seed_session(session_factory, older, title="Older", updated_at=now - timedelta(hours=1))
    await _seed_session(session_factory, newer, title="Newer", updated_at=now)

    await persist_summary(session_factory, older, "a summary written later")

    ids = [s["id"] for s in await list_sessions(session_factory, _ctx(user=1))]
    assert ids == ["sum-newer", "sum-older"], "summary write must not reorder the history list"


async def test_rehydrate_restores_summary(session_factory):
    ctx = _ctx(session="s-sum-rehydrate")
    await upsert_session(session_factory, ctx, first_user_message="hi")
    await persist_message(session_factory, ctx, "user", "older turn")
    await persist_summary(session_factory, ctx, "earlier condensed context")

    store = InMemorySessionStore()
    await _rehydrate_if_cold(store, session_factory, ctx)

    assert await store.get_summary(ctx) == "earlier condensed context"
