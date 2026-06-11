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

    assert mookit.write_calls == ["create_lecture", "upload_file", "attach_course_resource"]
    upload_kw = mookit.calls_to("upload_file")[0]
    attach_kw = mookit.calls_to("attach_course_resource")[0]
    assert upload_kw["entity_type"] == "lectures"
    assert attach_kw["entity_type"] == "lectures"
    assert upload_kw["entity_id"] == attach_kw["entity_id"]
    assert attach_kw["resources"][0]["resourceType"] == "video"
    assert attach_kw["resources"][0]["isPrimary"] is True


async def test_lecture_tool_emits_upload_id_without_mookit_id(ctx) -> None:
    reg = InMemoryArtifactRegistry()
    res = await DraftLectureTool(FakeMooKitClient(), reg).run(
        ctx, {"week_label": "Week 4", "file_artifact_id": "our-file-1"}
    )
    proposal = await PublishLectureTool(reg).run(ctx, {"draft_id": res.artifact_id})
    assert proposal.payload["_upload_file_id"] == "our-file-1"
    assert "_resource" not in proposal.payload
