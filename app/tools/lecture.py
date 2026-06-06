"""B3.3 — lecture tools.

  * DraftLectureTool (draft)   — resolve week/module + generate title → lecture_draft artifact.
  * PublishLectureTool (publish) — propose publishing with a diff preview. NEVER calls mooKIT.

Video upload is Dev A's file path; we reference the uploaded file_artifact_id and describe the
attach-as-course-resource step in the payload.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from app.contracts import (
    Artifact,
    ArtifactRegistry,
    ProposedAction,
    RequestContext,
    Tool,
    ToolResult,
)
from app.contracts.mookit import MooKitClient
from app.core.hashing import canonical_hash
from app.gen.lecture_meta import draft_lecture_meta
from app.gen.provenance import stamp
from app.llm.schema import strict_schema
from app.preview.render import build_lecture_preview


class DraftLectureArgs(BaseModel):
    week_label: str
    module_label: str | None = None
    file_artifact_id: str | None = None
    file_mookit_id: int | None = None  # mooKIT fileId of the uploaded video (for resource attach)
    release_on: int | None = None  # unix seconds; None => publish now


class DraftLectureTool(Tool):
    name = "draft_lecture"
    description = "Draft lecture metadata: resolve the week/module and generate a title."
    risk_tier = "draft"
    parameters_schema = strict_schema(DraftLectureArgs)
    required_permission = ("lectures", "create")

    def __init__(self, mookit: MooKitClient, registry: ArtifactRegistry) -> None:
        self._mookit = mookit
        self._registry = registry

    async def run(self, ctx: RequestContext, args: dict[str, Any]) -> ToolResult:
        parsed = DraftLectureArgs.model_validate(args)
        meta = await draft_lecture_meta(
            self._mookit,
            ctx,
            week_label=parsed.week_label,
            module_label=parsed.module_label,
            file_artifact_id=parsed.file_artifact_id,
            release_on=parsed.release_on,
        )
        payload = meta.model_dump()
        payload["file_mookit_id"] = parsed.file_mookit_id
        art = Artifact(
            id="",
            type="lecture_draft",
            title=meta.title,
            status="draft",
            payload=payload,
            provenance=stamp(
                ai_generated=True,
                edited_by_human=False,
                source_ids=[parsed.file_artifact_id] if parsed.file_artifact_id else [],
            ),
        )
        art_id = await self._registry.add(ctx, art)
        msg = (
            f"Drafted lecture '{meta.title}'."
            if not meta.ambiguous
            else f"Couldn't resolve '{parsed.week_label}'. Which week did you mean?"
        )
        return ToolResult(ok=True, artifact_id=art_id, data=meta.model_dump(), message=msg)


class PublishLectureArgs(BaseModel):
    draft_id: str


class PublishLectureTool(Tool):
    name = "publish_lecture"
    description = "Propose publishing/scheduling a lecture draft (requires confirmation)."
    risk_tier = "publish"
    parameters_schema = strict_schema(PublishLectureArgs)
    required_permission = ("lectures", "publish")

    def __init__(self, registry: ArtifactRegistry) -> None:
        self._registry = registry

    async def run(self, ctx: RequestContext, args: dict[str, Any]) -> ProposedAction:
        parsed = PublishLectureArgs.model_validate(args)
        draft = await self._registry.get(ctx, parsed.draft_id)
        if draft is None:
            raise KeyError(parsed.draft_id)
        d = draft.payload
        scheduled = d.get("release_on") is not None
        visibility = "scheduled" if scheduled else "published"
        schedule_label = _fmt_schedule(d.get("release_on"))
        attachments = [d["file_artifact_id"]] if d.get("file_artifact_id") else []

        # LectureCreate-compatible body (flat) + optional `_resource` magic key for the executor to
        # attach the uploaded video as a course resource. topicId defaults to 0 when no module.
        payload: dict[str, Any] = {
            "title": d["title"],
            "weekId": d.get("week_id"),
            "topicId": d.get("topic_id") or 0,
            "published": 0 if scheduled else 1,
            "releaseOn": d.get("release_on"),
            "provenance": draft.provenance,
        }
        file_id = d.get("file_mookit_id")
        if file_id is not None:
            payload["_resource"] = {
                "resourceType": "video",
                "resourceFileId": int(file_id),
                "isPrimary": True,
            }
        preview = build_lecture_preview(
            title=d["title"],
            week_label=d.get("week_label", ""),
            module_label=d.get("module_label"),
            visibility=visibility,
            schedule_label=schedule_label,
            attachments=attachments,
            description_markdown=d.get("description"),
        )
        return ProposedAction(
            action="publish_lecture",
            target_ref={"week_id": d.get("week_id"), "topic_id": d.get("topic_id"), "draft_id": parsed.draft_id},
            payload=payload,
            preview=preview,
            content_hash=canonical_hash(payload),
        )


def _fmt_schedule(release_on: int | None) -> str | None:
    if release_on is None:
        return None
    return datetime.fromtimestamp(release_on, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
