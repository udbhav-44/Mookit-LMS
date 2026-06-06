"""
Deterministic executor (A3.3 / A3.4) — integrated with Dev B's publish-tool payloads.

Maps a confirmed ProposedAction → typed MooKitClient write calls.

Key invariants:
  - All recipients / targets are resolved server-side from the stored action, never from model/doc text.
  - Every write path is explicitly enumerated; unknown actions raise ValueError.
  - Only reachable after the ConfirmationGate verifies the one-time token + content_hash — never from
    the model loop.

Payload shapes (produced by Dev B publish tools):
  publish_assessment: {_type, assessment: AssessmentCreate, questions: [QuestionCreate], citations,
                       provenance}  → create (status 0) → add questions → publish (status 1)
  send_announcement:  AnnouncementCreate fields + _audience_intent  → resolve audience → create
  publish_lecture:    LectureCreate fields + optional _resource + provenance  → create → attach resource
"""

from typing import Any

from ..contracts.context import RequestContext
from ..mookit.client import MooKitClient
from ..mookit.schemas import (
    AnnouncementCreate,
    AssessmentCreate,
    LectureCreate,
    QuestionCreate,
    SectionCreate,
)

# Maps action name → (resource, mooKIT action string) for permission re-validation.
ACTION_TO_RESOURCE: dict[str, tuple[str, str]] = {
    "create_assessment":   ("assessments", "create"),
    "update_assessment":   ("assessments", "update"),
    "publish_assessment":  ("assessments", "create"),
    "add_question":        ("assessments", "update"),
    "create_announcement": ("announcements", "create"),
    "send_announcement":   ("announcements", "create"),
    "create_lecture":      ("lectures", "create"),
    "publish_lecture":     ("lectures", "create"),
    "upload_file":         ("files", "upload"),
}


def _entity_id(result: Any) -> int | None:
    if isinstance(result, dict):
        return result.get("id")
    return getattr(result, "id", None)


class DeterministicExecutor:
    def __init__(self, mookit_client: MooKitClient, session_factory=None):
        self.mookit = mookit_client
        self.session_factory = session_factory  # for resolving stored uploads (FileMeta)

    async def execute(self, ctx: RequestContext, action: str, payload: dict) -> Any:
        """Execute a confirmed action against the live mooKIT API. All params come from storage."""
        if action == "publish_assessment":
            return await self._publish_assessment(ctx, payload)
        if action == "send_announcement":
            return await self._send_announcement(ctx, payload)
        if action == "publish_lecture":
            return await self._publish_lecture(ctx, payload)
        if action == "create_announcement":
            return await self._send_announcement(ctx, payload)
        if action == "upload_file":
            return await self._upload_file(ctx, payload)
        raise ValueError(f"Unknown confirmed action type: '{action}'")

    # ------------------------------------------------------------------
    # Assessment: create (draft) → add questions → publish (status 1)
    # ------------------------------------------------------------------
    async def _publish_assessment(self, ctx: RequestContext, payload: dict) -> Any:
        atype = str(payload.get("_type", "quizzes"))
        assessment_body = AssessmentCreate(**payload["assessment"])
        created = await self.mookit.create_assessment(ctx, atype, assessment_body)
        assessment_id = _entity_id(created)

        if assessment_id is not None:
            # mooKIT requires questions to live under a section; create one, then add questions to it.
            section = await self.mookit.create_section(
                ctx, atype, int(assessment_id),
                SectionCreate(title=payload.get("section_title", "Questions")),
            )
            section_id = _entity_id(section) or 0
            for q in payload.get("questions", []):
                await self.mookit.add_question(
                    ctx, atype, int(assessment_id), int(section_id), QuestionCreate(**q)
                )
            # Publish: flip published.status to 1.
            await self.mookit.update_assessment(
                ctx, atype, int(assessment_id), {"published": {"status": 1, "releaseOn": None}}
            )
        return created

    # ------------------------------------------------------------------
    # Announcement: resolve audience server-side → create with status=1
    # ------------------------------------------------------------------
    async def _send_announcement(self, ctx: RequestContext, payload: dict) -> Any:
        body_fields = {k: v for k, v in payload.items() if not k.startswith("_")}
        intent = payload.get("_audience_intent", "all")
        section_ids = await self._resolve_audience(ctx, intent)
        if section_ids is not None:
            body_fields["sectionIds"] = section_ids
        # Ensure published.
        published = dict(body_fields.get("published") or {})
        published["status"] = 1
        body_fields["published"] = published
        body = AnnouncementCreate(**body_fields)
        return await self.mookit.create_announcement(ctx, body)

    async def _resolve_audience(self, ctx: RequestContext, intent: str) -> list[int] | None:
        """Resolve an audience intent label to sectionIds. 'all'/empty → None (all students).

        Named sections are resolved via the section taxonomy server-side — never from model text.
        """
        if not intent or intent.strip().lower() in {"all", "everyone", "all students"}:
            return None
        try:
            terms = await self.mookit.list_taxonomy(ctx, "section")
        except Exception:
            return None
        norm = " ".join(intent.lower().split())
        matched = [t.id for t in terms if " ".join(t.name.lower().split()) == norm]
        return matched or None

    # ------------------------------------------------------------------
    # Lecture: create → attach video resource (if any)
    # ------------------------------------------------------------------
    async def _publish_lecture(self, ctx: RequestContext, payload: dict) -> Any:
        body_fields = {
            k: v for k, v in payload.items() if not k.startswith("_") and k != "provenance"
        }
        body = LectureCreate(**body_fields)
        lecture = await self.mookit.create_lecture(ctx, body)
        lecture_id = _entity_id(lecture)
        if lecture_id is None:
            return lecture

        # Resolve the video resource: either a ready mooKIT fileId (_resource) or a stored upload
        # (_upload_file_id) that we first push to mooKIT's /files/add to obtain a fileId.
        resource = payload.get("_resource")
        if resource is None and payload.get("_upload_file_id"):
            resource = await self._upload_stored_to_mookit(ctx, str(payload["_upload_file_id"]))
        if resource:
            await self.mookit.attach_course_resource(ctx, "lectures", int(lecture_id), [resource])
        return lecture

    async def _upload_stored_to_mookit(self, ctx: RequestContext, our_file_id: str) -> dict | None:
        """Push a locally-stored uploaded file to mooKIT (/files/add) and return a video resource."""
        meta = await self._lookup_file_meta(ctx, our_file_id)
        if meta is None:
            return None
        path, filename, mime = meta
        with open(path, "rb") as f:
            files = {"files": (filename, f, mime)}
            managed = await self.mookit.upload_file(ctx, files)
        if not managed:
            return None
        return {"resourceType": "video", "resourceFileId": managed[0].id, "isPrimary": True}

    async def _lookup_file_meta(self, ctx: RequestContext, our_file_id: str):
        if self.session_factory is None:
            return None
        from sqlalchemy import select

        from ..store.db import FileMeta
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(FileMeta).where(
                        FileMeta.id == our_file_id, FileMeta.tenant_key == ctx.tenant_key
                    )
                )
            ).scalar_one_or_none()
        if row is None:
            return None
        return (row.storage_path, row.filename, row.mime_type)

    # ------------------------------------------------------------------
    # File upload (server-side path)
    # ------------------------------------------------------------------
    async def _upload_file(self, ctx: RequestContext, payload: dict) -> Any:
        file_path = str(payload["_file_path"])
        filename = str(payload.get("filename", "upload"))
        entity_type = payload.get("entity_type")
        entity_id = int(payload.get("entity_id", 0))
        with open(file_path, "rb") as f:
            files = {"files": (filename, f, payload.get("mime_type", "application/octet-stream"))}
            return await self.mookit.upload_file(ctx, files, entity_type, entity_id)
