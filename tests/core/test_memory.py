"""B1.2 acceptance — compaction keeps recent verbatim + summary; draft survives; ops bump version."""

from app.contracts.types import Artifact
from app.core.memory import TranscriptManager, apply_operation, estimate_tokens
from tests.fakes.fake_stores import InMemoryArtifactRegistry, InMemorySessionStore


async def _seed_turns(store: InMemorySessionStore, ctx, n: int, *, size: int = 400) -> None:
    for i in range(n):
        await store.append_message(ctx, "user", f"turn {i} " + "x" * size)
        await store.append_message(ctx, "assistant", f"reply {i} " + "y" * size)


async def test_compaction_triggers_over_threshold(ctx) -> None:
    store = InMemorySessionStore()
    await _seed_turns(store, ctx, n=10)
    tm = TranscriptManager(store, max_tokens=500, keep_recent=4)
    compacted = await tm.maybe_compact(ctx)
    assert compacted is True
    summary = await store.get_summary(ctx)
    assert summary and len(summary) > 0


async def test_view_keeps_recent_plus_summary(ctx) -> None:
    store = InMemorySessionStore()
    await _seed_turns(store, ctx, n=10)
    tm = TranscriptManager(store, max_tokens=500, keep_recent=4)
    await tm.maybe_compact(ctx)
    view = await tm.view(ctx)
    assert view[0].role == "developer" and "summary" in view[0].content.lower()
    # The remaining (non-summary) messages are at most keep_recent.
    assert len(view) - 1 <= 4


async def test_no_compaction_under_threshold(ctx) -> None:
    store = InMemorySessionStore()
    await _seed_turns(store, ctx, n=1, size=10)
    tm = TranscriptManager(store, max_tokens=5000, keep_recent=8)
    assert await tm.maybe_compact(ctx) is False


async def test_draft_survives_compaction(ctx) -> None:
    """The headline test: a draft created early is unchanged after transcript compaction."""
    store = InMemorySessionStore()
    reg = InMemoryArtifactRegistry()
    draft_id = await reg.add(
        ctx,
        Artifact(id="", type="assessment_draft", title="Ch3 Quiz", status="draft", payload={"questions": [1, 2, 3]}),
    )
    await _seed_turns(store, ctx, n=12)
    tm = TranscriptManager(store, max_tokens=400, keep_recent=4)
    await tm.maybe_compact(ctx)
    survived = await reg.get(ctx, draft_id)
    assert survived is not None
    assert survived.payload == {"questions": [1, 2, 3]}
    assert survived.version == 1  # untouched by compaction


async def test_operation_bumps_version_not_prose(ctx) -> None:
    store = InMemorySessionStore()
    reg = InMemoryArtifactRegistry()
    draft_id = await reg.add(ctx, Artifact(id="", type="assessment_draft", title="Q", status="draft", payload={"n": 3}))
    updated = await apply_operation(reg, ctx, draft_id, {"payload": {"n": 8}})
    assert updated.version == 2
    assert updated.payload["n"] == 8
    # No prose was appended to the transcript.
    assert await store.get_transcript(ctx, max_tokens=1000) == []


def test_estimate_tokens() -> None:
    from app.contracts.types import Message

    assert estimate_tokens([Message(role="user", content="x" * 40)]) == 10
