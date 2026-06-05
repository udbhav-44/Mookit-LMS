from abc import ABC, abstractmethod
from typing import Any, List, Callable, Coroutine
import httpx
from .context import RequestContext, PermissionMatrix
from ..mookit.schemas import (
    AssessmentCreate, QuestionCreate, AnnouncementCreate, AnnouncementUpdate,
    LectureCreate, TaxonomyTerm, ManagedFile,
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
    async def list_taxonomy(self, ctx: RequestContext, type: str) -> List[TaxonomyTerm]: ...

    @abstractmethod
    async def create_assessment(self, ctx: RequestContext, type: str, body: AssessmentCreate) -> Any: ...

    @abstractmethod
    async def update_assessment(self, ctx: RequestContext, type: str, assessment_id: int, patch: dict) -> Any: ...

    @abstractmethod
    async def add_question(self, ctx: RequestContext, type: str, assessment_id: int, section_id: int, body: QuestionCreate) -> Any: ...

    @abstractmethod
    async def create_announcement(self, ctx: RequestContext, body: AnnouncementCreate) -> Any: ...

    @abstractmethod
    async def update_announcement(self, ctx: RequestContext, announcement_id: int, body: AnnouncementUpdate) -> Any: ...

    @abstractmethod
    async def upload_file(self, ctx: RequestContext, files: dict, entity_type: str | None = None, entity_id: int = 0) -> List[ManagedFile]: ...

    @abstractmethod
    async def create_lecture(self, ctx: RequestContext, body: LectureCreate) -> Any: ...

    @abstractmethod
    async def attach_course_resource(self, ctx: RequestContext, entity_type: str, entity_id: int, resources: List[dict]) -> List[Any]: ...
