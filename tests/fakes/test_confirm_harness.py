"""UK.4 acceptance — propose never writes; confirm writes once; reject never writes; stale voids."""

import pytest

from app.contracts.types import PreviewRender, ProposedAction
from tests.fakes.confirm_harness import ConfirmHarness, canonical_hash
from tests.fakes.fake_mookit import FakeMooKitClient
from tests.fakes.fake_rag import retrieve


def _announcement_action() -> ProposedAction:
    payload = {"title": "Exam reminder", "description": "Tomorrow", "type": "normal", "notifyMail": 1}
    return ProposedAction(
        action="send_announcement",
        target_ref={"audience": "all"},
        payload=payload,
        preview=PreviewRender(title="Send announcement"),
        content_hash=canonical_hash(payload),
    )


async def test_propose_does_not_write(ctx) -> None:
    mookit = FakeMooKitClient()
    harness = ConfirmHarness(mookit)
    harness.propose(ctx, _announcement_action())
    assert mookit.write_calls == []


async def test_confirm_writes_once(ctx) -> None:
    mookit = FakeMooKitClient()
    harness = ConfirmHarness(mookit)
    aid = harness.propose(ctx, _announcement_action())
    await harness.confirm(aid)
    assert mookit.write_calls == ["create_announcement"]


async def test_reject_never_writes(ctx) -> None:
    mookit = FakeMooKitClient()
    harness = ConfirmHarness(mookit)
    aid = harness.propose(ctx, _announcement_action())
    harness.reject(aid)
    assert mookit.write_calls == []
    assert harness.pending[aid].status == "rejected"


async def test_stale_hash_voids_token(ctx) -> None:
    mookit = FakeMooKitClient()
    harness = ConfirmHarness(mookit)
    aid = harness.propose(ctx, _announcement_action())
    with pytest.raises(ValueError, match="content_hash mismatch"):
        await harness.confirm(aid, current_hash="different")
    assert mookit.write_calls == []
    assert harness.pending[aid].status == "stale"


async def test_retrieve_returns_spans(ctx) -> None:
    spans = await retrieve(ctx, "doc-1", "photosynthesis chloroplast", k=2)
    assert len(spans) == 2
    assert all(s.locator.get("doc_id") == "sample" for s in spans)


async def test_retrieve_unknown_doc_empty(ctx) -> None:
    assert await retrieve(ctx, "missing", "anything") == []
