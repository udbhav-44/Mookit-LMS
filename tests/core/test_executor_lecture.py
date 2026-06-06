"""#11 — lecture video is uploaded to mooKIT at confirm time, then attached as the primary resource."""

import tempfile

from app.core.executor import DeterministicExecutor
from app.tools.lecture import DraftLectureTool, PublishLectureTool
from tests.fakes.fake_mookit import FakeMooKitClient
from tests.fakes.fake_stores import InMemoryArtifactRegistry


async def test_publish_lecture_uploads_stored_video(ctx, monkeypatch) -> None:
    mookit = FakeMooKitClient()
    executor = DeterministicExecutor(mookit)

    # Stand in for the FileMeta lookup (no DB): point at a real temp file.
    with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
        tmp.write(b"\x00\x00\x00\x18ftypmp42")
        tmp.flush()

        async def _fake_lookup(ctx_, fid):
            return (tmp.name, "lecture.mp4", "video/mp4")

        monkeypatch.setattr(executor, "_lookup_file_meta", _fake_lookup)

        payload = {
            "title": "Intro", "weekId": 104, "topicId": 0, "published": 1, "releaseOn": None,
            "_upload_file_id": "our-file-1",
        }
        await executor.execute(ctx, "publish_lecture", payload)

    assert "create_lecture" in mookit.write_calls
    assert "upload_file" in mookit.write_calls           # video pushed to mooKIT
    assert "attach_course_resource" in mookit.write_calls  # attached as resource


async def test_lecture_tool_emits_upload_id_without_mookit_id(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    res = await DraftLectureTool(FakeMooKitClient(), reg).run(
        ctx, {"week_label": "Week 4", "file_artifact_id": "our-file-1"}
    )
    proposal = await PublishLectureTool(reg).run(ctx, {"draft_id": res.artifact_id})
    assert proposal.payload["_upload_file_id"] == "our-file-1"
    assert "_resource" not in proposal.payload
