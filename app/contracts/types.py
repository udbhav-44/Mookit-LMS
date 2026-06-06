"""The 7 shared contracts (the seam between Dev A and Dev B).

These mirror `docs/plan/05-shared-contracts.md`. They are *co-owned* with Dev A and frozen at CP1.
Dev B builds the AI brain entirely against these types; Dev A's real infra plugs into the same seams.

Contract index:
    1. RequestContext           — per-request identity + tenancy
    2. Tool / ToolResult / ProposedAction — what Dev B authors, Dev A executes
    3. PreviewRender            — what the confirm dialog shows
    4. SessionStore / ArtifactRegistry / Artifact — memory seams
    5. LLMProvider              — swappable model provider
    6. SSE event schema         — wire format (see app/contracts/events or llm/events)
    7. MooKitClient             — typed async client over the live mooKIT API
"""

from __future__ import annotations

import builtins
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------

RiskTier = Literal["read", "draft", "publish"]
"""read/draft auto-run; publish must be confirmed via the deterministic gate."""

ArtifactType = Literal[
    "uploaded_file",
    "assessment_draft",
    "announcement_draft",
    "lecture_draft",
]


class ErrorInfo(BaseModel):
    """Typed error surfaced to the UI."""

    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] | None = None


class PermissionMatrix(BaseModel):
    """Cached result of GET /user_permissions/allowed.

    Shape: ``{resourceName: [actions...]}`` e.g. ``{"lectures": ["list", "create"]}``.
    """

    allowed: dict[str, list[str]] = Field(default_factory=dict)

    def can(self, resource: str, action: str) -> bool:
        return action in self.allowed.get(resource, [])


# ---------------------------------------------------------------------------
# Contract 1 — RequestContext
# ---------------------------------------------------------------------------


class RequestContext(BaseModel):
    """Per-request identity + tenancy, populated by Dev A's middleware, read by everyone."""

    instance_id: str  # e.g. "hello.iitk.ac.in" -> resolves to a mooKIT base URL
    course_id: str  # mooKIT "course" short-name (also the `course` header value)
    user_id: int  # mooKIT uid
    session_id: str
    forwarded_headers: dict[str, str] = Field(default_factory=dict)  # {course, token, uid}
    permissions: PermissionMatrix = Field(default_factory=PermissionMatrix)
    tenant_key: str = ""  # canonical "{instance_id}:{course_id}" — namespaces ALL storage/cache
    request_id: str = ""  # correlation id, propagated through SSE + ARQ jobs

    def model_post_init(self, __context: Any) -> None:
        if not self.tenant_key:
            object.__setattr__(self, "tenant_key", f"{self.instance_id}:{self.course_id}")


# ---------------------------------------------------------------------------
# Contract 3 — PreviewRender (defined before ProposedAction which references it)
# ---------------------------------------------------------------------------


class PreviewRender(BaseModel):
    """What the UI shows in the confirm dialog. Built by Dev B, rendered by the UI."""

    title: str
    summary_lines: list[str] = Field(default_factory=list)
    audience: str | None = None  # e.g. "142 students in CS101" (announcements/lectures)
    body_markdown: str | None = None  # rendered announcement / lecture description (sanitized)
    diff: list[dict[str, Any]] | None = None  # [{field, before, after}] for updates
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Contract 2 — Tool ABC + ToolResult / ProposedAction
# ---------------------------------------------------------------------------


class ToolResult(BaseModel):
    """Returned by read/draft tools — fed back to the model."""

    ok: bool
    data: Any = None
    artifact_id: str | None = None
    message: str | None = None
    error: ErrorInfo | None = None


class ProposedAction(BaseModel):
    """Returned by publish tools — NOT executed inline. Surfaced to the confirm gate."""

    action: str  # e.g. "publish_assessment", "send_announcement", "publish_lecture"
    target_ref: dict[str, Any]  # server-resolved target (e.g. {assessment_type, assessment_id})
    payload: dict[str, Any]  # exact mooKIT request body that WILL be sent
    preview: PreviewRender  # faithful human-readable render of what will happen
    content_hash: str  # sha256 of canonicalized payload; binds the confirm token


class Tool(ABC):
    """Dev B authors tools; Dev A's gate + client execute them.

    Subclasses set the class attributes and implement ``run``.
    """

    name: str  # snake_case, stable; appears in OpenAI tool schema + audit log
    description: str
    risk_tier: RiskTier
    parameters_schema: dict[str, Any]  # strict JSON Schema (additionalProperties:false, all required)
    # (resource, action) permission this tool needs; None ⇒ always visible (read-tier helpers).
    required_permission: tuple[str, str] | None = None

    @abstractmethod
    async def run(self, ctx: RequestContext, args: dict[str, Any]) -> ToolResult | ProposedAction:
        ...


# ---------------------------------------------------------------------------
# Contract 4 — SessionStore + ArtifactRegistry + Artifact + Message
# ---------------------------------------------------------------------------


class Message(BaseModel):
    role: str  # "user" | "assistant" | "system" | "tool"
    content: str
    meta: dict[str, Any] | None = None


class Artifact(BaseModel):
    id: str
    type: ArtifactType
    title: str
    status: str  # "uploaded" | "draft" | "published" | ...
    version: int = 1
    provenance: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    namespaced_id: str = ""  # "{tenant_key}:{user_id}:{id}" — durable, enables cross-session memory


class SessionStore(ABC):
    @abstractmethod
    async def append_message(
        self, ctx: RequestContext, role: str, content: str, meta: dict[str, Any] | None = None
    ) -> None: ...

    @abstractmethod
    async def get_transcript(self, ctx: RequestContext, *, max_tokens: int) -> list[Message]: ...

    @abstractmethod
    async def set_summary(self, ctx: RequestContext, summary: str) -> None: ...

    @abstractmethod
    async def get_summary(self, ctx: RequestContext) -> str | None: ...


class ArtifactRegistry(ABC):
    @abstractmethod
    async def add(self, ctx: RequestContext, art: Artifact) -> str: ...

    @abstractmethod
    async def get(self, ctx: RequestContext, artifact_id: str) -> Artifact | None: ...

    @abstractmethod
    async def update(self, ctx: RequestContext, artifact_id: str, patch: dict[str, Any]) -> Artifact: ...

    @abstractmethod
    async def list(
        self, ctx: RequestContext, *, type: str | None = None
    ) -> builtins.list[Artifact]: ...

    @abstractmethod
    async def focus(self, ctx: RequestContext) -> builtins.list[str]: ...  # recent first

    @abstractmethod
    async def push_focus(self, ctx: RequestContext, artifact_id: str) -> None: ...


# ---------------------------------------------------------------------------
# Contract 5 — LLMProvider ABC + LLMEvent stream
# ---------------------------------------------------------------------------


class LLMEvent(BaseModel):
    """Base class for the typed event stream emitted by LLMProvider.respond()."""

    kind: str


class AssistantDelta(LLMEvent):
    kind: Literal["assistant_delta"] = "assistant_delta"
    text: str


class ToolCallStarted(LLMEvent):
    kind: Literal["tool_call_started"] = "tool_call_started"
    call_id: str
    name: str


class ToolCallArgsDelta(LLMEvent):
    kind: Literal["tool_call_args_delta"] = "tool_call_args_delta"
    call_id: str
    delta: str


class ToolCallArgsDone(LLMEvent):
    kind: Literal["tool_call_args_done"] = "tool_call_args_done"
    call_id: str
    name: str
    arguments: dict[str, Any]


class ResponseCompleted(LLMEvent):
    kind: Literal["response_completed"] = "response_completed"
    response_id: str
    usage: dict[str, Any] | None = None


class ErrorEvent(LLMEvent):
    kind: Literal["error"] = "error"
    code: str
    message: str
    retryable: bool = False


class LLMProvider(ABC):
    """Dev B implements with OpenAI Responses API. Swappable per spec §12."""

    @abstractmethod
    def respond(
        self,
        *,
        instructions: str,
        input: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        parallel_tool_calls: bool = True,
        previous_response_id: str | None = None,
        stream: bool = True,
        prompt_cache_key: str | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[LLMEvent]: ...

    @abstractmethod
    async def respond_structured(
        self,
        *,
        instructions: str,
        input: list[dict[str, Any]],
        schema: type[BaseModel],
        prompt_cache_key: str | None = None,
        temperature: float | None = None,
    ) -> BaseModel: ...
