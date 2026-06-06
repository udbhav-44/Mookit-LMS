"""B3.3 acceptance — taxonomy resolution, diff preview, schedule→releaseOn, propose-not-execute."""

from app.contracts.types import ProposedAction, ToolResult
from app.tools.lecture import DraftLectureTool, PublishLectureTool
from tests.fakes.fake_mookit import FakeMooKitClient
from tests.fakes.fake_stores import InMemoryArtifactRegistry


async def _draft(ctx, reg, mookit, **kw):
    res = await DraftLectureTool(mookit, reg).run(ctx, kw)
    assert isinstance(res, ToolResult)
    return res.artifact_id, res


async def test_resolves_week(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    mookit = FakeMooKitClient()
    aid, _ = await _draft(ctx, reg, mookit, week_label="Week 4", file_artifact_id="art_9")
    draft = await reg.get(ctx, aid)
    assert draft.payload["week_id"] == 104
    assert draft.payload["ambiguous"] is False


async def test_unknown_week_marked_ambiguous(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    mookit = FakeMooKitClient()
    _, res = await _draft(ctx, reg, mookit, week_label="Week 99")
    assert res.data["ambiguous"] is True
    assert "which week" in res.message.lower()


async def test_publish_proposes_with_diff(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    mookit = FakeMooKitClient()
    aid, _ = await _draft(ctx, reg, mookit, week_label="Week 4", file_artifact_id="art_9")
    result = await PublishLectureTool(reg).run(ctx, {"draft_id": aid})
    assert isinstance(result, ProposedAction)
    assert result.action == "publish_lecture"
    assert result.preview.diff
    assert result.payload["lecture"]["weekId"] == 104


async def test_schedule_sets_release_on(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    mookit = FakeMooKitClient()
    aid, _ = await _draft(ctx, reg, mookit, week_label="Week 4", release_on=1893456000)
    result = await PublishLectureTool(reg).run(ctx, {"draft_id": aid})
    assert result.payload["lecture"]["releaseOn"] == 1893456000
    assert result.payload["lecture"]["published"] == 0  # scheduled, not immediately published
