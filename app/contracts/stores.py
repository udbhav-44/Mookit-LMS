from abc import ABC, abstractmethod
from typing import Literal, Any, List
from pydantic import BaseModel
from .context import RequestContext

class Message(BaseModel):
    role: str
    content: str
    meta: dict | None = None

class Artifact(BaseModel):
    id: str
    type: Literal["uploaded_file", "assessment_draft", "announcement_draft", "lecture_draft"]
    title: str
    status: str                        # "uploaded" | "draft" | "published" | ...
    version: int
    provenance: dict                   # {created_by, ai_generated: bool, edited_by_human: bool, source_ids}
    payload: dict                      # the structured object (quiz questions, announcement fields, ...)
    namespaced_id: str                 # "{tenant_key}:{user_id}:{id}" — durable, enables future cross-session memory

class SessionStore(ABC):
    @abstractmethod
    async def append_message(self, ctx: RequestContext, role: str, content: str, meta: dict | None = None) -> None: ...
    
    @abstractmethod
    async def get_transcript(self, ctx: RequestContext, *, max_tokens: int) -> List[Message]: ...
    
    @abstractmethod
    async def set_summary(self, ctx: RequestContext, summary: str) -> None: ...

class ArtifactRegistry(ABC):
    @abstractmethod
    async def add(self, ctx: RequestContext, art: Artifact) -> str: ...
    
    @abstractmethod
    async def get(self, ctx: RequestContext, artifact_id: str) -> Artifact | None: ...
    
    @abstractmethod
    async def update(self, ctx: RequestContext, artifact_id: str, patch: dict) -> Artifact: ...
    
    @abstractmethod
    async def list(self, ctx: RequestContext, *, type: str | None = None) -> List[Artifact]: ...
    
    @abstractmethod
    async def focus(self, ctx: RequestContext) -> List[str]: ...
    
    @abstractmethod
    async def push_focus(self, ctx: RequestContext, artifact_id: str) -> None: ...
