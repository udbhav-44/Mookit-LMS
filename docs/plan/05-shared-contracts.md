# 05 — Shared Contracts (the seam between Dev A and Dev B)

These interfaces are **frozen at the end of P0 (CP1)**. Once frozen, Dev A and Dev B build against them  
independently — Dev A tests the full request→mooKIT→confirm→audit path with a *stub tool*; Dev B tests  
the agent + quiz pipeline against a *fake `MooKitClient`* and an *in-memory `SessionStore`*. They only  
meet at these 7 contracts. Put them in a shared package: `app/contracts/`.

---

## Contract 1 — `RequestContext`

Per-request identity + tenancy, populated by Dev A's middleware, read by everyone.

```python
class RequestContext(BaseModel):
    instance_id: str            # e.g. "hello.iitk.ac.in"  -> resolves to a mooKIT base URL
    course_id: str              # mooKIT "course" short-name (also the `course` header value)
    user_id: int                # mooKIT uid
    session_id: str
    forwarded_headers: dict[str, str]   # {course, token, uid} — passed straight to mooKIT, never logged raw
    permissions: PermissionMatrix       # cached result of GET /user_permissions/allowed
    tenant_key: str             # canonical "{instance_id}:{course_id}" — namespaces ALL storage/cache
    request_id: str             # correlation id, propagated through SSE + ARQ jobs
```

## Contract 2 — `Tool` ABC + `ToolResult` / `ProposedAction`

Dev B authors tools; Dev A's gate + client execute them.

```python
RiskTier = Literal["read", "draft", "publish"]   # read/draft auto-run; publish must be confirmed

class Tool(ABC):
    name: str                          # snake_case, stable; appears in OpenAI tool schema + audit log
    description: str
    risk_tier: RiskTier
    parameters_schema: dict            # strict JSON Schema (additionalProperties:false, all required)

    @abstractmethod
    async def run(self, ctx: RequestContext, args: dict) -> "ToolResult | ProposedAction": ...

class ToolResult(BaseModel):           # returned by read/draft tools — fed back to the model
    ok: bool
    data: Any = None
    artifact_id: str | None = None     # if the tool created/updated an artifact
    message: str | None = None
    error: ErrorInfo | None = None

class ProposedAction(BaseModel):       # returned by publish tools — NOT executed inline
    action: str                        # e.g. "publish_assessment", "send_announcement", "publish_lecture"
    target_ref: dict                   # server-resolved target (e.g. {assessment_type, assessment_id})
    payload: dict                      # exact mooKIT request body that WILL be sent
    preview: PreviewRender             # faithful human-readable render of what will happen
    content_hash: str                  # sha256 of canonicalized payload; binds the confirm token
```

## Contract 3 — `PreviewRender`

What the UI shows in the confirm dialog. Built by Dev B, rendered by the UI (Dev A wires it).

```python
class PreviewRender(BaseModel):
    title: str                         # "Publish quiz: Chapter 3 Quiz"
    summary_lines: list[str]           # bullet summary of the change
    audience: str | None = None        # e.g. "142 students in CS101"  (announcements/lectures)
    body_markdown: str | None = None   # rendered announcement / lecture description (sanitized)
    diff: list[dict] | None = None     # [{field, before, after}] for updates
    warnings: list[str] = []           # e.g. "5 questions are higher-order Bloom — review carefully"
```

## Contract 4 — `SessionStore` + `ArtifactRegistry`

Dev A implements (Redis + Postgres); Dev B consumes. Keyed by `tenant_key` + `session_id`.

```python
class SessionStore(ABC):
    async def append_message(self, ctx, role: str, content: str, meta: dict | None = None) -> None: ...
    async def get_transcript(self, ctx, *, max_tokens: int) -> list[Message]: ...   # compacted view
    async def set_summary(self, ctx, summary: str) -> None: ...

class ArtifactRegistry(ABC):
    async def add(self, ctx, art: "Artifact") -> str: ...                 # returns artifact_id
    async def get(self, ctx, artifact_id: str) -> "Artifact | None": ...
    async def update(self, ctx, artifact_id: str, patch: dict) -> "Artifact": ...   # bumps version
    async def list(self, ctx, *, type: str | None = None) -> list["Artifact"]: ...
    async def focus(self, ctx) -> list[str]: ...                          # focus stack (recent first)
    async def push_focus(self, ctx, artifact_id: str) -> None: ...

class Artifact(BaseModel):
    id: str
    type: Literal["uploaded_file", "assessment_draft", "announcement_draft", "lecture_draft"]
    title: str
    status: str                        # "uploaded" | "draft" | "published" | ...
    version: int
    provenance: dict                   # {created_by, ai_generated: bool, edited_by_human: bool, source_ids}
    payload: dict                      # the structured object (quiz questions, announcement fields, ...)
    namespaced_id: str                 # "{tenant_key}:{user_id}:{id}" — durable, enables future cross-session memory
```

## Contract 5 — `LLMProvider` ABC

Dev B implements with OpenAI Responses API. Swappable per spec .

```python
class LLMProvider(ABC):
    async def respond(self, *, instructions: str, input: list[dict], tools: list[dict],
                      tool_choice="auto", parallel_tool_calls: bool = True,
                      previous_response_id: str | None = None,
                      stream: bool = True, prompt_cache_key: str | None = None) -> AsyncIterator[LLMEvent]: ...

    async def respond_structured(self, *, instructions: str, input: list[dict],
                                 schema: type[BaseModel], prompt_cache_key: str | None = None) -> BaseModel: ...
```

## Contract 6 — SSE event schema

The wire format from service → UI. Both devs depend on it.

```
event: assistant_delta        data: {"text": "..."}                       # streamed prose tokens
event: tool_started           data: {"tool": "create_quiz", "label": "Generating quiz…"}
event: tool_progress          data: {"tool": "...", "pct": 40, "message": "12/30 questions"}
event: artifact_updated       data: {"artifact_id": "...", "type": "assessment_draft", "version": 2}
event: pending_confirmation   data: {"action_id": "...", "preview": PreviewRender, "expires_at": ...}
event: error                  data: {"code": "...", "message": "...", "retryable": bool}
event: done                   data: {"response_id": "..."}
```

## Contract 7 — `MooKitClient`

Typed async client over the live mooKIT API. Dev A owns; Dev B calls it from tools.

```python
class MooKitClient:
    def __init__(self, http: httpx.AsyncClient, base_url_resolver: Callable[[str], str]): ...
    async def call(self, ctx: RequestContext, method: str, path: str,
                   *, json: dict | None = None, params: dict | None = None,
                   files: dict | None = None) -> Any: ...   # injects course/token/uid, unwraps envelope, maps errors
    # plus typed helpers, e.g.:
    async def create_assessment(self, ctx, type: str, body: AssessmentCreate) -> Assessment: ...
    async def add_question(self, ctx, type, assessment_id, section_id, body: QuestionCreate) -> Question: ...
    async def create_announcement(self, ctx, body: AnnouncementCreate) -> Announcement: ...
    async def upload_file(self, ctx, files, entity_type=None, entity_id=0) -> list[ManagedFile]: ...
    async def create_lecture(self, ctx, body: LectureCreate) -> Lecture: ...
    async def attach_course_resource(self, ctx, entity_type, entity_id, resources: list[dict]) -> list[CourseResource]: ...
    async def list_taxonomy(self, ctx, type: str) -> list[TaxonomyTerm]: ...
    async def get_permissions(self, ctx) -> PermissionMatrix: ...
```

---

### Stubs to ship at CP1 

- Dev A ships: `FakeMooKitClient` (returns canned objects), real `RequestContext` middleware, in-memory `SessionStore`/`ArtifactRegistry`.
- Dev B ships: `EchoTool` (read tier), a minimal `OpenAIProvider.respond` that streams, and the system-prompt skeleton.
- Both: agree on the exact JSON Schema dialect for tool parameters (OpenAI strict mode → all properties `required`, `additionalProperties:false`, optionals modeled as `["type","null"]`).

