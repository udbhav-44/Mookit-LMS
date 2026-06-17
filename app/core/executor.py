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

import logging
from typing import Any

from ..contracts.context import RequestContext
from ..diagrams.pipeline import get_diagram_result
from ..mookit.client import MooKitClient
from ..mookit.schemas import (
    AnnouncementCreate,
    AssessmentCreate,
    CourseResourceCreate,
    LectureCreate,
    QuestionCreate,
    SectionCreate,
)

logger = logging.getLogger(__name__)

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


def _match_diagram(question_text: str, diagram_map: "dict[str, int]") -> "int | None":
    """Return the mooKIT fileId whose stored question_text best matches `question_text`.

    Uses word-overlap (Jaccard) so minor rephrasing between the PDF extractor and the
    quiz generator doesn't break the match. Requires at least 30% overlap to avoid false
    positives when a document has many short questions.
    """
    if not diagram_map or not question_text:
        return None
    q_words = set(question_text.lower().split())
    best_score = 0.0
    best_id: int | None = None
    for stored_text, file_id in diagram_map.items():
        s_words = set(stored_text.lower().split())
        union = q_words | s_words
        if not union:
            continue
        score = len(q_words & s_words) / len(union)
        if score > best_score:
            best_score = score
            best_id = file_id
    return best_id if best_score >= 0.30 else None


def _entity_id(result: Any) -> int | None:
    if isinstance(result, dict):
        return result.get("id")
    return getattr(result, "id", None)


class DeterministicExecutor:
    def __init__(self, mookit_client: MooKitClient, session_factory=None, redis=None):
        self.mookit = mookit_client
        self.session_factory = session_factory  # for resolving stored uploads (FileMeta)
        self._redis = redis                     # for reading diagram extraction results

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
            # Build a question_text → mooKIT fileId map from any diagram results stored for the
            # source documents. Diagrams are uploaded to mooKIT here (once) before questions are
            # created so we can attach the returned mooKIT fileId via QuestionCreate.fileIds.
            source_ids: list[str] = (
                payload.get("provenance", {}).get("source_ids")
                or payload.get("source_artifact_ids")
                or []
            )
            diagram_file_ids = await self._upload_diagrams_for_assessment(
                ctx, atype, source_ids, assessment_id
            )

            # mooKIT requires questions to live under a section; create one, then add questions to it.
            section = await self.mookit.create_section(
                ctx, atype, int(assessment_id),
                SectionCreate(title=payload.get("section_title", "Questions")),
            )
            section_id = _entity_id(section) or 0
            for q in payload.get("questions", []):
                # Inject diagram fileId if one was matched for this question's text.
                q = dict(q)
                q_text = q.get("questionText", "")
                matched_file_id = _match_diagram(q_text, diagram_file_ids)
                if matched_file_id is not None:
                    existing = q.get("fileIds") or []
                    q["fileIds"] = list({*existing, matched_file_id})
                await self.mookit.add_question(
                    ctx, atype, int(assessment_id), int(section_id), QuestionCreate(**q)
                )
            # Publish: flip published.status to 1.
            await self.mookit.update_assessment(
                ctx, atype, int(assessment_id), {"published": {"status": 1, "releaseOn": None}}
            )
        return created

    async def _upload_diagrams_for_assessment(
        self, ctx: RequestContext, atype: str, source_ids: list[str], assessment_id: Any
    ) -> "dict[str, int]":
        """Return {question_text: mooKIT_file_id} for every diagram linked to the source docs.

        Uploads each cropped diagram PNG to mooKIT /files/add scoped to the new assessment so
        it is stored as a managed file and its integer id can be passed to QuestionCreate.fileIds.
        Failures are non-fatal — a missing diagram never blocks question creation.

        `entityType` must be the concrete assessment type (`quizzes`/`exams`/`assignments`);
        mooKIT has no generic `assessments` upload entity, so the literal string is rejected by
        its upload middleware as an unexpected multipart field (HTTP 500 "Unexpected field").
        """
        if not self._redis or not source_ids:
            return {}

        result: dict[str, int] = {}
        for doc_id in source_ids:
            try:
                diagram_result = await get_diagram_result(self._redis, ctx.tenant_key, doc_id)
            except Exception as exc:
                logger.warning("Could not load diagram result for doc_id=%s: %s", doc_id, exc)
                continue
            if diagram_result is None or not diagram_result.diagrams:
                continue

            for info in diagram_result.diagrams:
                try:
                    with open(info.diagram_path, "rb") as f:
                        managed = await self.mookit.upload_file(
                            ctx,
                            {"files": (info.diagram_file, f, "image/png")},
                            entity_type=atype,
                            entity_id=int(assessment_id),
                            # Diagrams are non-fatal: a flaky upload endpoint must not trip the
                            # circuit breaker and block the mandatory create/publish calls below.
                            best_effort=True,
                        )
                    if managed:
                        result[info.question_text] = managed[0].id
                        logger.info(
                            "Uploaded diagram for question '%.60s' → mooKIT fileId=%d",
                            info.question_text, managed[0].id,
                        )
                except Exception as exc:
                    logger.warning(
                        "Failed to upload diagram %s: %s", info.diagram_file, exc
                    )
        return result

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

        Safety: if the instructor targeted a *specific* section but it cannot be verified (lookup
        failure) or does not match any course section, we RAISE rather than fall back to "all
        students". Silently broadcasting to the whole course on a typo or a transient error is a
        far worse failure than refusing the send.
        """
        if not intent or intent.strip().lower() in {"all", "everyone", "all students", "all_students"}:
            return None
        try:
            terms = await self.mookit.list_taxonomy(ctx, "section")
        except Exception as exc:
            raise ValueError(
                f"Couldn't verify the target audience '{intent}' (section lookup failed). "
                "Refusing to broadcast to all students by mistake — try again, or send to "
                "'all students' explicitly if that's the intent."
            ) from exc
        norm = " ".join(intent.lower().split())
        matched = [t.id for t in terms if " ".join(t.name.lower().split()) == norm]
        if not matched:
            available = ", ".join(t.name for t in terms) or "(none)"
            raise ValueError(
                f"Audience '{intent}' didn't match any course section, so this was NOT sent "
                f"(refusing to broadcast to everyone by mistake). Available sections: {available}. "
                "Pick a valid section or say 'all students'."
            )
        return matched

    # ------------------------------------------------------------------
    # Lecture (mooKIT video flow):
    #   1. POST /lectures
    #   2. POST /files/add  (entityType=lectures, entityId=<lecture id>)
    #   3. POST /lectures/{id}/course-resources  (one primary video resource)
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

        resource = self._coerce_resource(payload.get("_resource"))
        if resource is None and payload.get("_upload_file_id"):
            resource = await self._upload_stored_to_mookit(
                ctx, str(payload["_upload_file_id"]), lecture_id=int(lecture_id)
            )
        if resource:
            await self.mookit.attach_course_resource(
                ctx, "lectures", int(lecture_id), [resource.model_dump()]
            )
        return lecture

    @staticmethod
    def _coerce_resource(raw: dict | None) -> CourseResourceCreate | None:
        if not raw:
            return None
        return CourseResourceCreate(
            resourceType=raw.get("resourceType", "video"),
            resourceFileId=int(raw["resourceFileId"]),
            isPrimary=bool(raw.get("isPrimary", True)),
        )

    async def _upload_stored_to_mookit(
        self, ctx: RequestContext, our_file_id: str, *, lecture_id: int
    ) -> CourseResourceCreate | None:
        """Step 2: push our stored video to mooKIT /files/add scoped to the new lecture."""
        meta = await self._lookup_file_meta(ctx, our_file_id)
        if meta is None:
            return None
        path, filename, mime = meta
        with open(path, "rb") as f:
            files = {"files": (filename, f, mime)}
            managed = await self.mookit.upload_file(
                ctx, files, entity_type="lectures", entity_id=lecture_id
            )
        if not managed:
            return None
        return CourseResourceCreate(
            resourceType="video",
            resourceFileId=managed[0].id,
            isPrimary=True,
        )

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
