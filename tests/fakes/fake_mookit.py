"""UK.2 — FakeMooKitClient.

Canned, schema-valid responses for every endpoint Dev B's tools touch. Records calls for assertions.
Satisfies the ``MooKitClient`` Protocol so it drops straight into the tool/orchestrator wiring.
"""

from __future__ import annotations

from typing import Any

from app.contracts.mookit import (
    Announcement,
    Assessment,
    CourseResource,
    Lecture,
    ManagedFile,
    Question,
    TaxonomyTerm,
    User,
)
from app.contracts.types import PermissionMatrix, RequestContext

# Default permission matrix granting all Phase-1 actions.
ALL_PERMISSIONS = PermissionMatrix(
    allowed={
        "assessments": ["list", "create", "update", "delete", "publish"],
        "questions": ["create", "update", "delete"],
        "announcements": ["create", "publish", "update", "delete"],
        "lectures": ["list", "create", "update", "delete", "publish"],
        "files": ["upload", "delete"],
        "taxonomies": ["list"],
        "users": ["read"],
    }
)

# Seeded taxonomy terms. "Week 4" is explicitly present (used by reference/taxonomy tests).
_TAXONOMY: dict[str, list[TaxonomyTerm]] = {
    "week": [
        TaxonomyTerm(id=101, title="Week 1", type="week"),
        TaxonomyTerm(id=102, title="Week 2", type="week"),
        TaxonomyTerm(id=103, title="Week 3", type="week"),
        TaxonomyTerm(id=104, title="Week 4", type="week"),
    ],
    "module": [
        TaxonomyTerm(id=201, title="Module 1", type="module"),
        TaxonomyTerm(id=202, title="Module 2", type="module"),
    ],
    "topic": [
        TaxonomyTerm(id=301, title="Introduction", type="topic"),
        TaxonomyTerm(id=302, title="Advanced Topics", type="topic"),
    ],
}


class FakeMooKitClient:
    """In-memory test double for the mooKIT API."""

    def __init__(self, *, permissions: PermissionMatrix | None = None) -> None:
        self.permissions = permissions or ALL_PERMISSIONS
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._next_id = 1000

    def _mint_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _record(self, method: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((method, args, kwargs))

    # -- generic ----------------------------------------------------------
    async def call(
        self,
        ctx: RequestContext,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> Any:
        self._record("call", method=method, path=path, json=json, params=params)
        return {"ok": True, "path": path}

    # -- read paths -------------------------------------------------------
    async def get_permissions(self, ctx: RequestContext) -> PermissionMatrix:
        self._record("get_permissions")
        return self.permissions

    async def whoami(self, ctx: RequestContext) -> User:
        self._record("whoami")
        return User(id=ctx.user_id, name="Test Instructor", email="instructor@example.edu")

    async def list_taxonomy(self, ctx: RequestContext, type: str) -> list[TaxonomyTerm]:
        self._record("list_taxonomy", type=type)
        return list(_TAXONOMY.get(type, []))

    # -- write paths (these are only reachable via the confirm executor / harness) -
    async def create_assessment(
        self, ctx: RequestContext, type: str, body: dict[str, Any]
    ) -> Assessment:
        self._record("create_assessment", type=type, body=body)
        return Assessment(id=self._mint_id(), title=body.get("title", "Untitled"))

    async def add_question(
        self,
        ctx: RequestContext,
        type: str,
        assessment_id: int,
        section_id: int,
        body: dict[str, Any],
    ) -> Question:
        self._record(
            "add_question",
            type=type,
            assessment_id=assessment_id,
            section_id=section_id,
            body=body,
        )
        return Question(id=self._mint_id(), questionType=body.get("questionType", "mcq_single"))

    async def create_announcement(self, ctx: RequestContext, body: dict[str, Any]) -> Announcement:
        self._record("create_announcement", body=body)
        return Announcement(id=self._mint_id(), title=body.get("title", "Untitled"))

    async def upload_file(
        self,
        ctx: RequestContext,
        files: dict[str, Any],
        entity_type: str | None = None,
        entity_id: int = 0,
    ) -> list[ManagedFile]:
        self._record("upload_file", entity_type=entity_type, entity_id=entity_id)
        return [ManagedFile(id=self._mint_id(), fileUrl="https://files/test", filemime="video/mp4")]

    async def create_lecture(self, ctx: RequestContext, body: dict[str, Any]) -> Lecture:
        self._record("create_lecture", body=body)
        return Lecture(id=self._mint_id(), title=body.get("title", "Untitled"))

    async def attach_course_resource(
        self,
        ctx: RequestContext,
        entity_type: str,
        entity_id: int,
        resources: list[dict[str, Any]],
    ) -> list[CourseResource]:
        self._record(
            "attach_course_resource",
            entity_type=entity_type,
            entity_id=entity_id,
            resources=resources,
        )
        return [CourseResource(id=self._mint_id())]

    # -- test helpers -----------------------------------------------------
    def calls_to(self, method: str) -> list[tuple[Any, ...]]:
        return [(args, kwargs) for (m, args, kwargs) in self.calls if m == method]

    @property
    def write_calls(self) -> list[str]:
        writes = {
            "create_assessment",
            "add_question",
            "create_announcement",
            "upload_file",
            "create_lecture",
            "attach_course_resource",
        }
        return [m for (m, _a, _k) in self.calls if m in writes]
