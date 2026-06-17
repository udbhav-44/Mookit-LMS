"""ConfirmationGate.revise_announcement (audience / email / schedule / attachments) + executor.

Gate runs against in-memory SQLite. The executor runs for real against the fake mooKIT client to
prove: a scheduled announcement carries published.status=0 + releaseOn; a section audience resolves
to sectionIds; and an unknown section id is refused fail-closed at confirm time.
"""

from __future__ import annotations

import time

import pytest
import pytest_asyncio
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.confirmation import ConfirmationGate, _canonical_hash
from app.core.executor import DeterministicExecutor
from app.store.db import Base, PendingAction
from tests.fakes.fake_mookit import FakeMooKitClient

_DAY = 86400


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _payload() -> dict:
    return {
        "title": "Class update",
        "description": "Body text.",
        "type": "normal",
        "notifyMail": 0,
        "published": {"status": 1, "releaseOn": None},
        "_audience_intent": "all",
    }


async def _seed(factory, tenant_key="t:c") -> str:
    payload = _payload()
    async with factory() as s:
        await s.execute(insert(PendingAction).values(
            id="act-1", tenant_key=tenant_key, action="send_announcement",
            target_ref={}, payload=payload, content_hash=_canonical_hash(payload),
            confirm_token="tok", status="pending",
        ))
        await s.commit()
    return "act-1"


@pytest.mark.asyncio
async def test_schedule_sets_status_zero_and_release(session_factory):
    aid = await _seed(session_factory)
    gate = ConfirmationGate(session_factory)
    future = int(time.time()) + 3 * _DAY
    revised = await gate.revise_announcement(
        aid, "t:c", title="Class update", description="Body text.",
        notify_mail=1, schedule_at=future,
    )
    pub = revised.payload["published"]
    assert pub["status"] == 0 and pub["releaseOn"] == future
    assert revised.payload["notifyMail"] == 1


@pytest.mark.asyncio
async def test_section_audience_resolves_to_sectionids(session_factory, ctx):
    aid = await _seed(session_factory, tenant_key=ctx.tenant_key)
    gate = ConfirmationGate(session_factory)
    revised = await gate.revise_announcement(
        aid, ctx.tenant_key, title="Class update", description="Body text.",
        audience=401, audience_label="Section 1",
    )
    assert revised.payload["_audience_section_id"] == 401

    mookit = FakeMooKitClient()
    await DeterministicExecutor(mookit).execute(ctx, "send_announcement", dict(revised.payload))
    create = [kw for (m, kw) in mookit.calls if m == "create_announcement"]
    assert create and create[0]["body"].sectionIds == [401]


@pytest.mark.asyncio
async def test_unknown_section_id_refused_at_confirm(session_factory, ctx):
    aid = await _seed(session_factory, tenant_key=ctx.tenant_key)
    gate = ConfirmationGate(session_factory)
    revised = await gate.revise_announcement(
        aid, ctx.tenant_key, title="Class update", description="Body text.",
        audience=9999, audience_label="Ghost section",
    )
    mookit = FakeMooKitClient()
    with pytest.raises(ValueError):
        await DeterministicExecutor(mookit).execute(ctx, "send_announcement", dict(revised.payload))
    assert not [m for (m, _) in mookit.calls if m == "create_announcement"]
