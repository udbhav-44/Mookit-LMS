"""
Deterministic executor (A3.3 / A3.4).

Maps a confirmed ProposedAction → typed MooKitClient write calls.

Key invariants enforced here:
  - All recipients / targets are resolved server-side from the stored action,
    never from model or document text.
  - Every write path is explicitly enumerated — unknown actions raise ValueError
    so they are never silently executed.
  - The executor is only reachable after the ConfirmationGate has verified the
    one-time token and content_hash — it is never called from the model loop.
"""

from typing import Any

from ..contracts.context import RequestContext
from ..mookit.client import MooKitClient
from ..mookit.schemas import (
    AssessmentCreate,
    QuestionCreate,
    AnnouncementCreate,
    LectureCreate,
)


# Maps action name → (resource, mooKIT action string) for permission re-validation.
# This is the same mapping as in auth/permissions.py — kept in sync manually.
ACTION_TO_RESOURCE: dict[str, tuple[str, str]] = {
    "create_assessment":   ("assessments", "create"),
    "update_assessment":   ("assessments", "update"),
    "publish_assessment":  ("assessments", "update"),
    "add_question":        ("assessments", "update"),
    "create_announcement": ("announcements", "create"),
    "send_announcement":   ("announcements", "create"),
    "create_lecture":      ("lectures", "create"),
    "publish_lecture":     ("lectures", "update"),
    "upload_file":         ("files", "upload"),
}


class DeterministicExecutor:
    def __init__(self, mookit_client: MooKitClient):
        self.mookit = mookit_client

    async def execute(self, ctx: RequestContext, action: str, payload: dict) -> Any:
        """Execute a confirmed action against the live mooKIT API.

        `action` is the action-type string stored in PendingAction.action.
        `payload` is the exact body that was stored and hash-verified.
        All parameters come from server-side storage — never from request input.
        """
        if action == "create_assessment":
            return await self._create_assessment(ctx, payload)

        if action == "update_assessment":
            return await self._update_assessment(ctx, payload)

        if action == "publish_assessment":
            # Publishing = updating published.status to 1 on an existing assessment.
            return await self._publish_assessment(ctx, payload)

        if action == "add_question":
            return await self._add_question(ctx, payload)

        if action == "create_announcement":
            return await self._create_announcement(ctx, payload)

        if action == "send_announcement":
            # Sending = creating an announcement with published.status=1.
            payload = {**payload, "published": {**payload.get("published", {}), "status": 1}}
            return await self._create_announcement(ctx, payload)

        if action == "create_lecture":
            return await self._create_lecture(ctx, payload)

        if action == "publish_lecture":
            return await self._publish_lecture(ctx, payload)

        if action == "upload_file":
            return await self._upload_file(ctx, payload)

        raise ValueError(f"Unknown confirmed action type: '{action}'")

    # ------------------------------------------------------------------
    # Private typed write helpers
    # ------------------------------------------------------------------

    async def _create_assessment(self, ctx: RequestContext, payload: dict) -> Any:
        assessment_type = str(payload.pop("_type", "quizzes"))
        body = AssessmentCreate(**payload)
        return await self.mookit.create_assessment(ctx, assessment_type, body)

    async def _update_assessment(self, ctx: RequestContext, payload: dict) -> Any:
        assessment_type = str(payload.pop("_type", "quizzes"))
        assessment_id = int(payload.pop("_id"))
        return await self.mookit.update_assessment(ctx, assessment_type, assessment_id, payload)

    async def _publish_assessment(self, ctx: RequestContext, payload: dict) -> Any:
        assessment_type = str(payload.pop("_type", "quizzes"))
        assessment_id = int(payload.pop("_id"))
        patch = {"published": {"status": 1, "releaseOn": payload.get("releaseOn")}}
        return await self.mookit.update_assessment(ctx, assessment_type, assessment_id, patch)

    async def _add_question(self, ctx: RequestContext, payload: dict) -> Any:
        assessment_type = str(payload.pop("_type", "quizzes"))
        assessment_id = int(payload.pop("_assessment_id"))
        section_id = int(payload.pop("_section_id"))
        body = QuestionCreate(**payload)
        return await self.mookit.add_question(ctx, assessment_type, assessment_id, section_id, body)

    async def _create_announcement(self, ctx: RequestContext, payload: dict) -> Any:
        body = AnnouncementCreate(**payload)
        return await self.mookit.create_announcement(ctx, body)

    async def _create_lecture(self, ctx: RequestContext, payload: dict) -> Any:
        resource = payload.pop("_resource", None)   # optional attached file dict
        body = LectureCreate(**payload)
        lecture = await self.mookit.create_lecture(ctx, body)

        if resource and lecture:
            lecture_id = lecture.get("id")
            if lecture_id:
                await self.mookit.attach_course_resource(
                    ctx, "lectures", int(lecture_id), [resource]
                )
        return lecture

    async def _publish_lecture(self, ctx: RequestContext, payload: dict) -> Any:
        # Publish = update lecture with published=1 via PUT /lectures/{id}
        lecture_id = int(payload.pop("_id"))
        patch = {"published": 1, "releaseOn": payload.get("releaseOn")}
        return await self.mookit.call(ctx, "PUT", f"/lectures/{lecture_id}", json=patch)

    async def _upload_file(self, ctx: RequestContext, payload: dict) -> Any:
        # Files are uploaded from server-side storage — the file_path is a server path.
        file_path = str(payload["_file_path"])
        filename = str(payload.get("filename", "upload"))
        entity_type = payload.get("entity_type")
        entity_id = int(payload.get("entity_id", 0))

        with open(file_path, "rb") as f:
            files = {"files": (filename, f, payload.get("mime_type", "application/octet-stream"))}
            return await self.mookit.upload_file(ctx, files, entity_type, entity_id)
