"""ConfirmationGate.revise_assessment + executor honouring revised dates.

The gate is exercised against an in-memory SQLite session factory (the models use the generic JSON
column type, so they create cleanly on SQLite). We assert the revised settings land on
``payload["assessment"]``, the content_hash changes, bad date ordering is rejected, and the real
DeterministicExecutor publishes with the revised dates (via the fake mooKIT client recorder).
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
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def _base_payload() -> dict:
    now = int(time.time())
    return {
        "_type": "quizzes",
        "assessment": {
            "title": "Photosynthesis Quiz",
            "startDate": now,
            "endDate": now + 7 * _DAY,
            "endDapDate": now + 7 * _DAY,
            "resultsDate": now + 8 * _DAY,
            "published": {"status": 0, "releaseOn": None},
            "timed": 0,
        },
        "questions": [
            {"questionType": "mcq_single", "questionText": "Q1", "score": 1,
             "negativeScore": 0, "published": {"status": 1}},
        ],
        "citations": [],
        "provenance": {},
    }


async def _seed(factory, payload: dict, tenant_key: str = "t:c") -> str:
    action_id = "act-1"
    async with factory() as s:
        await s.execute(insert(PendingAction).values(
            id=action_id, tenant_key=tenant_key, action="publish_assessment",
            target_ref={}, payload=payload, content_hash=_canonical_hash(payload),
            confirm_token="tok", status="pending",
        ))
        await s.commit()
    return action_id


@pytest.mark.asyncio
async def test_revise_writes_settings_and_changes_hash(session_factory):
    payload = _base_payload()
    original_hash = _canonical_hash(payload)
    action_id = await _seed(session_factory, payload)
    gate = ConfirmationGate(session_factory)

    now = int(time.time())
    revised = await gate.revise_assessment(
        action_id, "t:c",
        assessment_type="exams",
        start_date=now, end_date=now + 14 * _DAY, end_dap_date=now + 14 * _DAY,
        results_date=now + 15 * _DAY, timed=1, duration=45,
        instructions="Closed book.", show_correct_answers=1, retake_allowed=1,
    )
    assert revised is not None
    a = revised.payload["assessment"]
    assert revised.payload["_type"] == "exams"
    assert a["endDate"] == now + 14 * _DAY
    assert a["timed"] == 1 and a["duration"] == 45
    assert a["showCorrectAnswers"] == 1 and a["retakeAllowed"] == 1
    assert a["instructions"] == "Closed book."
    assert revised.content_hash != original_hash
    assert revised.content_hash == _canonical_hash(revised.payload)


@pytest.mark.asyncio
async def test_revise_rejects_bad_date_order(session_factory):
    action_id = await _seed(session_factory, _base_payload())
    gate = ConfirmationGate(session_factory)
    now = int(time.time())
    with pytest.raises(ValueError):
        await gate.revise_assessment(
            action_id, "t:c", assessment_type="quizzes",
            start_date=now + 10 * _DAY, end_date=now,  # end before start
            end_dap_date=now, results_date=now,
        )


@pytest.mark.asyncio
async def test_revise_requires_duration_when_timed(session_factory):
    action_id = await _seed(session_factory, _base_payload())
    gate = ConfirmationGate(session_factory)
    now = int(time.time())
    with pytest.raises(ValueError):
        await gate.revise_assessment(
            action_id, "t:c", assessment_type="quizzes",
            start_date=now, end_date=now + _DAY, end_dap_date=now + _DAY,
            results_date=now + 2 * _DAY, timed=1, duration=None,
        )


@pytest.mark.asyncio
async def test_executor_publishes_with_revised_dates(session_factory, ctx):
    """After revise, the executor builds under an editable future window, then applies the
    instructor's revised schedule via a final update_assessment (avoids mooKIT's active-window 409)."""
    action_id = await _seed(session_factory, _base_payload(), tenant_key=ctx.tenant_key)
    gate = ConfirmationGate(session_factory)
    now = int(time.time())
    revised = await gate.revise_assessment(
        action_id, ctx.tenant_key, assessment_type="quizzes",
        start_date=now, end_date=now + 21 * _DAY, end_dap_date=now + 21 * _DAY,
        results_date=now + 22 * _DAY,
    )
    mookit = FakeMooKitClient()
    executor = DeterministicExecutor(mookit)
    await executor.execute(ctx, "publish_assessment", dict(revised.payload))

    # Phase 1: created under a far-future, unpublished window so it stays editable while we add Qs.
    create_calls = [kw for (m, kw) in mookit.calls if m == "create_assessment"]
    assert create_calls, "expected create_assessment to be called"
    build_body = create_calls[0]["body"]
    assert build_body.startDate > now + _DAY, "build window must start well in the future"
    assert build_body.published == {"status": 0, "releaseOn": None}

    # Phase 2: the revised schedule + publish status is applied in the final update_assessment.
    update_calls = [kw for (m, kw) in mookit.calls if m == "update_assessment"]
    assert update_calls, "expected a final update_assessment to apply the real schedule"
    patch = update_calls[-1]["patch"]
    assert patch["endDate"] == now + 21 * _DAY
    assert patch["resultsDate"] == now + 22 * _DAY
