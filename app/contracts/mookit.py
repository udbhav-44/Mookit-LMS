"""Contract 7 — MooKitClient interface + light schema models.

Dev A owns the concrete typed client (built from the pinned OpenAPI spec). Dev B only needs the
*interface* to type tools against, plus thin models for the objects tools touch. These mirror the
payload shapes in ``docs/plan/09-mookit-api-reference.md`` and are intentionally permissive
(``extra="allow"``) so the real client can return richer objects without breaking Dev B.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from app.contracts.types import PermissionMatrix, RequestContext


class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class User(_Loose):
    id: int
    name: str | None = None
    email: str | None = None


class TaxonomyTerm(_Loose):
    id: int
    title: str
    type: str | None = None


class Assessment(_Loose):
    id: int
    title: str


class Question(_Loose):
    id: int
    questionType: str  # noqa: N815 (mooKIT field name)


class Announcement(_Loose):
    id: int
    title: str


class Lecture(_Loose):
    id: int
    title: str


class ManagedFile(_Loose):
    id: int
    fileUrl: str | None = None  # noqa: N815
    filemime: str | None = None
    filesize: int | None = None


class CourseResource(_Loose):
    id: int


@runtime_checkable
class MooKitClient(Protocol):
    """Typed async client over the live mooKIT API. Dev A owns; Dev B calls from tools."""

    async def call(
        self,
        ctx: RequestContext,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> Any: ...

    async def get_permissions(self, ctx: RequestContext) -> PermissionMatrix: ...

    async def whoami(self, ctx: RequestContext) -> User: ...

    async def list_taxonomy(self, ctx: RequestContext, type: str) -> list[TaxonomyTerm]: ...

    async def create_assessment(
        self, ctx: RequestContext, type: str, body: dict[str, Any]
    ) -> Assessment: ...

    async def add_question(
        self,
        ctx: RequestContext,
        type: str,
        assessment_id: int,
        section_id: int,
        body: dict[str, Any],
    ) -> Question: ...

    async def create_announcement(self, ctx: RequestContext, body: dict[str, Any]) -> Announcement: ...

    async def upload_file(
        self,
        ctx: RequestContext,
        files: dict[str, Any],
        entity_type: str | None = None,
        entity_id: int = 0,
    ) -> list[ManagedFile]: ...

    async def create_lecture(self, ctx: RequestContext, body: dict[str, Any]) -> Lecture: ...

    async def attach_course_resource(
        self,
        ctx: RequestContext,
        entity_type: str,
        entity_id: int,
        resources: list[dict[str, Any]],
    ) -> list[CourseResource]: ...
