"""Recording FakeMooKitClient — conforms to the canonical MooKitClient ABC.

Richer than Dev A's app.mookit.client.FakeMooKitClient: seeds Week 1-4 taxonomy and records every
call (incl. a `write_calls` list) so tests can assert the propose→confirm→write path.
"""

from __future__ import annotations

from typing import Any

from app.contracts.context import PermissionMatrix, RequestContext
from app.contracts.mookit import MooKitClient
from app.mookit.schemas import (
    AnnouncementCreate,
    AnnouncementUpdate,
    AssessmentCreate,
    LectureCreate,
    ManagedFile,
    QuestionCreate,
    TaxonomyTerm,
    UserMe,
)

ALL_PERMISSIONS = PermissionMatrix(
    resources={
        "assessments": ["list", "create", "update", "delete", "publish"],
        "announcements": ["list", "create", "update", "delete", "publish"],
        "lectures": ["list", "create", "update", "delete", "publish"],
        "files": ["upload", "delete"],
        "taxonomies": ["list"],
        "users": ["list", "view"],
    }
)

_TAXONOMY: dict[str, list[TaxonomyTerm]] = {
    "week": [TaxonomyTerm(id=100 + i, name=f"Week {i}", type="week") for i in range(1, 5)],
    "module": [TaxonomyTerm(id=200 + i, name=f"Module {i}", type="module") for i in range(1, 3)],
    "topic": [
        TaxonomyTerm(id=301, name="Introduction", type="topic"),
        TaxonomyTerm(id=302, name="Advanced Topics", type="topic"),
    ],
    "section": [TaxonomyTerm(id=400 + i, name=f"Section {i}", type="section") for i in range(1, 4)],
}

_WRITE_METHODS = {
    "create_assessment",
    "update_assessment",
    "add_question",
    "create_announcement",
    "update_announcement",
    "upload_file",
    "create_lecture",
    "attach_course_resource",
}


class FakeMooKitClient(MooKitClient):
    def __init__(self, *, permissions: PermissionMatrix | None = None) -> None:
        self.permissions = permissions or ALL_PERMISSIONS
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._next_id = 1000

    def _mint(self) -> int:
        self._next_id += 1
        return self._next_id

    def _record(self, method: str, **kw: Any) -> None:
        self.calls.append((method, kw))

    async def call(self, ctx: RequestContext, method: str, path: str, **kwargs: Any) -> Any:
        self._record("call", method=method, path=path)
        return {"ok": True, "path": path}

    async def users_me(self, ctx: RequestContext) -> UserMe:
        self._record("users_me")
        return UserMe(id=ctx.user_id, name="Test Instructor", email="instructor@example.edu", rolename="instructor")

    async def get_permissions(self, ctx: RequestContext) -> PermissionMatrix:
        self._record("get_permissions")
        return self.permissions

    async def list_taxonomy(self, ctx: RequestContext, type: str) -> list[TaxonomyTerm]:
        self._record("list_taxonomy", type=type)
        return list(_TAXONOMY.get(type, []))

    async def create_assessment(self, ctx: RequestContext, type: str, body: AssessmentCreate) -> Any:
        self._record("create_assessment", type=type, body=body)
        return {"id": self._mint(), "type": type, "title": body.title}

    async def update_assessment(self, ctx: RequestContext, type: str, assessment_id: int, patch: dict) -> Any:
        self._record("update_assessment", type=type, assessment_id=assessment_id, patch=patch)
        return {"id": assessment_id, **patch}

    async def add_question(self, ctx, type, assessment_id, section_id, body: QuestionCreate) -> Any:
        self._record("add_question", type=type, assessment_id=assessment_id, section_id=section_id, body=body)
        return {"id": self._mint(), "questionType": body.questionType}

    async def create_announcement(self, ctx: RequestContext, body: AnnouncementCreate) -> Any:
        self._record("create_announcement", body=body)
        return {"id": self._mint(), "title": body.title}

    async def update_announcement(self, ctx: RequestContext, announcement_id: int, body: AnnouncementUpdate) -> Any:
        self._record("update_announcement", announcement_id=announcement_id, body=body)
        return {"id": announcement_id}

    async def upload_file(self, ctx, files, entity_type=None, entity_id=0) -> list[ManagedFile]:
        self._record("upload_file", entity_type=entity_type, entity_id=entity_id)
        return [ManagedFile(id=self._mint(), fileUrl="https://files/test", filemime="video/mp4", filesize=1024, filename="v.mp4")]

    async def create_lecture(self, ctx: RequestContext, body: LectureCreate) -> Any:
        self._record("create_lecture", body=body)
        return {"id": self._mint(), "title": body.title}

    async def attach_course_resource(self, ctx, entity_type, entity_id, resources) -> list[Any]:
        self._record("attach_course_resource", entity_type=entity_type, entity_id=entity_id, resources=resources)
        return [{"id": self._mint(), **r} for r in resources]

    # -- test helpers --
    @property
    def write_calls(self) -> list[str]:
        return [m for (m, _kw) in self.calls if m in _WRITE_METHODS]

    def calls_to(self, method: str) -> list[dict[str, Any]]:
        return [kw for (m, kw) in self.calls if m == method]
