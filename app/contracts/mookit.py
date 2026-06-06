from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from .context import PermissionMatrix, RequestContext

# Type-only import to avoid a circular import (app.mookit package eagerly imports its client,
# which imports this module). Annotations are strings (PEP 563) so these are never needed at runtime.
if TYPE_CHECKING:
    from ..mookit.schemas import (
        AnnouncementCreate,
        AnnouncementUpdate,
        AssessmentCreate,
        LectureCreate,
        ManagedFile,
        QuestionCreate,
        SectionCreate,
        TaxonomyTerm,
    )

class MooKitClient(ABC):
    @abstractmethod
    async def call(self, ctx: RequestContext, method: str, path: str,
                   *, json: dict | None = None, params: dict | None = None,
                   files: dict | None = None) -> Any: ...

    @abstractmethod
    async def users_me(self, ctx: RequestContext) -> Any: ...

    @abstractmethod
    async def get_permissions(self, ctx: RequestContext) -> PermissionMatrix: ...

    @abstractmethod
    async def list_taxonomy(self, ctx: RequestContext, type: str) -> list[TaxonomyTerm]: ...

    @abstractmethod
    async def create_assessment(self, ctx: RequestContext, type: str, body: AssessmentCreate) -> Any: ...

    @abstractmethod
    async def update_assessment(self, ctx: RequestContext, type: str, assessment_id: int, patch: dict) -> Any: ...

    @abstractmethod
    async def create_section(self, ctx: RequestContext, type: str, assessment_id: int, body: SectionCreate) -> Any: ...

    @abstractmethod
    async def add_question(self, ctx: RequestContext, type: str, assessment_id: int, section_id: int, body: QuestionCreate) -> Any: ...

    @abstractmethod
    async def create_announcement(self, ctx: RequestContext, body: AnnouncementCreate) -> Any: ...

    @abstractmethod
    async def update_announcement(self, ctx: RequestContext, announcement_id: int, body: AnnouncementUpdate) -> Any: ...

    @abstractmethod
    async def upload_file(self, ctx: RequestContext, files: dict, entity_type: str | None = None, entity_id: int = 0) -> list[ManagedFile]: ...

    @abstractmethod
    async def create_lecture(self, ctx: RequestContext, body: LectureCreate) -> Any: ...

    @abstractmethod
    async def attach_course_resource(self, ctx: RequestContext, entity_type: str, entity_id: int, resources: list[dict]) -> list[Any]: ...
