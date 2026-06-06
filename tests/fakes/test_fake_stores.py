"""UK.3 acceptance — version bump, focus ordering, tenant isolation."""

from app.contracts.types import Artifact, RequestContext
from tests.fakes.fake_stores import InMemoryArtifactRegistry, InMemorySessionStore


def _art(title: str = "Draft", type_: str = "assessment_draft") -> Artifact:
    return Artifact(id="", type=type_, title=title, status="draft")


async def test_update_bumps_version(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    aid = await reg.add(ctx, _art())
    got = await reg.get(ctx, aid)
    assert got is not None and got.version == 1
    updated = await reg.update(ctx, aid, {"title": "New"})
    assert updated.version == 2
    assert updated.title == "New"


async def test_payload_patch_merges(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    aid = await reg.add(ctx, Artifact(id="", type="assessment_draft", title="Q", status="draft", payload={"a": 1}))
    updated = await reg.update(ctx, aid, {"payload": {"b": 2}})
    assert updated.payload == {"a": 1, "b": 2}


async def test_focus_recent_first(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    a1 = await reg.add(ctx, _art("One"))
    a2 = await reg.add(ctx, _art("Two"))
    assert await reg.focus(ctx) == [a2, a1]
    await reg.push_focus(ctx, a1)
    assert await reg.focus(ctx) == [a1, a2]


async def test_tenant_isolation(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    other = RequestContext(
        instance_id="other.iitk.ac.in", course_id="c2", user_id=2, session_id="s2"
    )
    aid = await reg.add(ctx, _art())
    assert await reg.get(ctx, aid) is not None
    assert await reg.get(other, aid) is None
    assert await reg.list(other) == []


async def test_session_store_summary(ctx) -> None:
    store = InMemorySessionStore()
    await store.append_message(ctx, "user", "hello")
    await store.set_summary(ctx, "a summary")
    assert (await store.get_summary(ctx)) == "a summary"
    transcript = await store.get_transcript(ctx, max_tokens=1000)
    assert len(transcript) == 1 and transcript[0].content == "hello"
