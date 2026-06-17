import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from ..contracts.context import PermissionMatrix, RequestContext
from ..contracts.mookit import MooKitClient as IMooKitClient
from .errors import (
    CircuitOpenError,
    MooKitRateLimitError,
    MooKitServerError,
    map_http_error,
)
from .schemas import (
    AnnouncementCreate,
    AnnouncementUpdate,
    AssessmentCreate,
    LectureCreate,
    ManagedFile,
    QuestionCreate,
    SectionCreate,
    TaxonomyTerm,
    UserMe,
)

logger = logging.getLogger(__name__)


class _CircuitBreaker:
    """Simple per-instance async circuit breaker (Closed → Open → Half-Open)."""

    def __init__(self, fail_max: int = 5, reset_seconds: float = 30.0):
        self._fail_max = fail_max
        self._reset_seconds = reset_seconds
        self._failures = 0
        self._state = "closed"
        self._last_failure: float = 0.0

    def _transition(self) -> None:
        if self._state == "open":
            if time.monotonic() - self._last_failure >= self._reset_seconds:
                self._state = "half_open"

    def record_success(self) -> None:
        self._failures = 0
        self._state = "closed"

    def record_failure(self) -> None:
        self._failures += 1
        self._last_failure = time.monotonic()
        if self._failures >= self._fail_max:
            self._state = "open"

    async def call(self, coro_factory: "Callable[[], Any]", *, record: bool = True):
        """Run `coro_factory()` under the breaker.

        `coro_factory` is a zero-arg callable returning a coroutine — NOT a coroutine — so
        that when the breaker is open we never create (and then orphan) an un-awaited
        coroutine. `record=False` lets best-effort calls fail without tripping the breaker
        that guards the critical write path, while still fast-failing when it is already open.
        """
        self._transition()
        if self._state == "open":
            raise CircuitOpenError("mooKIT")
        try:
            result = await coro_factory()
            if record:
                self.record_success()
            return result
        except (MooKitRateLimitError, MooKitServerError, httpx.HTTPError):
            if record:
                self.record_failure()
            raise
        except Exception:
            # Non-retryable errors (auth, 404) don't trip the breaker
            raise


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, (MooKitRateLimitError, MooKitServerError, httpx.ConnectError,
                            httpx.ReadTimeout, httpx.WriteTimeout))


# mooKIT's /user_permissions/allowed returns {data:{permissions:{resource:{viewEntity,manageOwn,
# manageOthers}}}} with int flags. Map that to our action-list PermissionMatrix that the tools use.
_MANAGE_ACTIONS = ["create", "update", "delete", "publish", "upload", "add", "edit"]
_VIEW_ACTIONS = ["list", "view", "read"]


def _flags_to_actions(flags: dict) -> list[str]:
    actions: list[str] = []
    if flags.get("viewEntity"):
        actions += _VIEW_ACTIONS
    if flags.get("manageOwn") or flags.get("manageOthers"):
        actions += _MANAGE_ACTIONS
    return actions


def _to_permission_matrix(data: dict) -> PermissionMatrix:
    perms = data.get("permissions", data) if isinstance(data, dict) else {}
    resources: dict[str, list[str]] = {}
    for resource, flags in perms.items():
        if isinstance(flags, dict):
            resources[resource] = _flags_to_actions(flags)
        elif isinstance(flags, list):  # already action-list shape (e.g. cached/fake)
            resources[resource] = flags
    # Our tools authorize against an "assessments" resource; mooKIT splits it into
    # quizzes/exams/assignments. Aggregate them so a user who can manage any may create assessments.
    agg: list[str] = []
    for r in ("quizzes", "exams", "assignments"):
        agg += resources.get(r, [])
    if agg:
        resources.setdefault("assessments", sorted(set(agg)))
    return PermissionMatrix(resources=resources)


class MooKitClient(IMooKitClient):
    """
    Typed async HTTP client for the mooKIT Instructor Express API.

    All requests inject {course, token, uid} from the RequestContext.
    The base URL is resolved per-request via `base_url_resolver(instance_id)`.
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        base_url_resolver: Callable[[str], str],
        fail_max: int = 5,
        reset_seconds: float = 30.0,
    ):
        self.http = http
        self._base_url_resolver = base_url_resolver
        self._breaker = _CircuitBreaker(fail_max=fail_max, reset_seconds=reset_seconds)

    # ------------------------------------------------------------------
    # Low-level call
    # ------------------------------------------------------------------

    async def call(
        self,
        ctx: RequestContext,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        files: dict | None = None,
        best_effort: bool = False,
    ) -> Any:
        """Send a request to mooKIT, unwrap the envelope, raise typed errors.

        URL scheme: {base_url}/{course}{path}, e.g.
            https://test.mookit.in/v2/api / coursetest / /users/me
        The course short-name is part of the path (course-scoped routing); it is also sent as a header.
        """
        base_url = self._base_url_resolver(ctx.instance_id).rstrip("/")
        course = ctx.course_id or ctx.forwarded_headers.get("course", "")
        norm_path = path if path.startswith("/") else f"/{path}"
        url = f"{base_url}/{course}{norm_path}"
        headers = {
            "course": ctx.forwarded_headers.get("course", ""),
            "token": ctx.forwarded_headers.get("token", ""),
            "uid": ctx.forwarded_headers.get("uid", ""),
            "x-request-id": ctx.request_id,
        }

        @retry(
            retry=retry_if_exception_type((MooKitRateLimitError, MooKitServerError,
                                           httpx.ConnectError, httpx.ReadTimeout)),
            stop=stop_after_attempt(3),
            wait=wait_random_exponential(multiplier=0.5, min=0.5, max=10),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        async def _request() -> Any:
            try:
                resp = await self.http.request(
                    method, url,
                    headers=headers,
                    json=json,
                    params=params,
                    files=files,
                )
            except httpx.HTTPError as exc:
                logger.warning("mooKIT HTTP transport error: %s", exc)
                raise

            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 1))
                raise MooKitRateLimitError(retry_after=retry_after)

            try:
                data = resp.json()
            except Exception as json_err:
                raise MooKitServerError(
                    f"Non-JSON response ({resp.status_code})", code=resp.status_code
                ) from json_err

            if resp.status_code >= 500:
                msg = data.get("error", {}).get("message", resp.text) if isinstance(data, dict) else resp.text
                raise MooKitServerError(msg, code=resp.status_code)

            if not data.get("success"):
                err = data.get("error", {})
                raise map_http_error(
                    err.get("code", resp.status_code),
                    err.get("message", "Unknown error"),
                    err.get("details"),
                )

            return data.get("data")

        # Pass the factory (not a coroutine) so an open breaker never orphans a coroutine.
        # best_effort calls don't trip the breaker that guards the critical write path.
        return await self._breaker.call(_request, record=not best_effort)

    # ------------------------------------------------------------------
    # Users / Permissions / Taxonomy
    # ------------------------------------------------------------------

    async def users_me(self, ctx: RequestContext) -> UserMe:
        data = await self.call(ctx, "GET", "/users/me")
        return UserMe.model_validate(data)

    async def get_permissions(self, ctx: RequestContext) -> PermissionMatrix:
        data = await self.call(ctx, "GET", "/user_permissions/allowed")
        return _to_permission_matrix(data if isinstance(data, dict) else {})

    async def list_taxonomy(self, ctx: RequestContext, type: str) -> list[TaxonomyTerm]:
        data = await self.call(ctx, "GET", f"/taxonomies/{type}")
        # Spec returns a direct array in data; fall back to .items for paginated responses.
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("items", [])
        else:
            items = []
        return [TaxonomyTerm(**item) for item in items]

    # ------------------------------------------------------------------
    # Assessments
    # ------------------------------------------------------------------

    async def create_assessment(self, ctx: RequestContext, type: str, body: AssessmentCreate) -> Any:
        return await self.call(ctx, "POST", f"/assessments/{type}", json=body.model_dump(exclude_none=True))

    async def update_assessment(self, ctx: RequestContext, type: str, assessment_id: int, patch: dict) -> Any:
        return await self.call(ctx, "PUT", f"/assessments/{type}/{assessment_id}", json=patch)

    async def create_section(
        self, ctx: RequestContext, type: str, assessment_id: int, body: SectionCreate
    ) -> Any:
        path = f"/assessments/{type}/{assessment_id}/sections"
        section_body = body.model_dump(exclude_none=True)
        # mooKIT cross-validates randomQuestionCount against randomizeQuestions. If the field is
        # *omitted* while randomization is off, mooKIT server-defaults it to 0 and then rejects the
        # request ("Random Question Count must be null when Randomize Questions is disabled"). So send
        # it explicitly: null when off, and the (required, >=1) value when on.
        if body.randomizeQuestions == 1:
            section_body["randomQuestionCount"] = body.randomQuestionCount
        else:
            section_body["randomQuestionCount"] = None
        return await self.call(ctx, "POST", path, json=section_body)

    async def add_question(
        self,
        ctx: RequestContext,
        type: str,
        assessment_id: int,
        section_id: int,
        body: QuestionCreate,
    ) -> Any:
        path = f"/assessments/{type}/{assessment_id}/sections/{section_id}/questions"
        return await self.call(ctx, "POST", path, json=body.model_dump(exclude_none=True))

    # ------------------------------------------------------------------
    # Announcements
    # ------------------------------------------------------------------

    async def create_announcement(self, ctx: RequestContext, body: AnnouncementCreate) -> Any:
        # Live mooKIT uses REST collection routes (POST /announcements), not the /add alias the
        # bundled OpenAPI spec documents — verified against test.mookit.in (the /add path 404s).
        return await self.call(ctx, "POST", "/announcements", json=body.model_dump(exclude_none=True))

    async def update_announcement(self, ctx: RequestContext, announcement_id: int, body: AnnouncementUpdate) -> Any:
        return await self.call(
            ctx, "PUT", f"/announcements/{announcement_id}",
            json=body.model_dump(exclude_none=True),
        )

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    async def upload_file(
        self,
        ctx: RequestContext,
        files: dict,
        entity_type: str | None = None,
        entity_id: int = 0,
        best_effort: bool = False,
    ) -> list[ManagedFile]:
        params: dict = {}
        if entity_type:
            params["entityType"] = entity_type
        if entity_id:
            params["entityId"] = entity_id
        data = await self.call(
            ctx, "POST", "/files/add", files=files, params=params, best_effort=best_effort
        )
        items = data if isinstance(data, list) else [data]
        return [ManagedFile(**item) for item in items]

    # ------------------------------------------------------------------
    # Lectures / Course Resources
    # ------------------------------------------------------------------

    async def create_lecture(self, ctx: RequestContext, body: LectureCreate) -> Any:
        return await self.call(ctx, "POST", "/lectures", json=body.model_dump(exclude_none=True))

    async def attach_course_resource(
        self,
        ctx: RequestContext,
        entity_type: str,
        entity_id: int,
        resources: list[dict],
    ) -> list[Any]:
        # Spec: POST /{entityType}/{entityId}/course-resources with body {"resources": [...]}
        path = f"/{entity_type}/{entity_id}/course-resources"
        data = await self.call(ctx, "POST", path, json={"resources": resources})
        return data if isinstance(data, list) else [data]


# ---------------------------------------------------------------------------
# Fake client for Dev B + unit tests
# ---------------------------------------------------------------------------

class FakeMooKitClient(IMooKitClient):
    """Returns canned responses for every endpoint; safe to use without network."""

    async def call(self, ctx: RequestContext, method: str, path: str, **kwargs: Any) -> Any:
        return {}

    async def users_me(self, ctx: RequestContext) -> UserMe:
        return UserMe(id=ctx.user_id, name="Test User", email="test@example.com",
                      rolename="instructor")

    async def get_permissions(self, ctx: RequestContext) -> PermissionMatrix:
        return PermissionMatrix(resources={
            "assessments": ["list", "create", "update", "delete"],
            "announcements": ["list", "create", "update", "delete"],
            "lectures": ["list", "create", "update", "delete"],
            "files": ["upload", "delete"],
            "users": ["list", "view"],
        })

    async def list_taxonomy(self, ctx: RequestContext, type: str) -> list[TaxonomyTerm]:
        return [TaxonomyTerm(id=1, name=f"{type.capitalize()} 1", type=type)]

    async def create_assessment(self, ctx: RequestContext, type: str, body: AssessmentCreate) -> Any:
        return {"id": 123, "type": type, "title": body.title}

    async def update_assessment(self, ctx: RequestContext, type: str, assessment_id: int, patch: dict) -> Any:
        return {"id": assessment_id, **patch}

    async def create_section(self, ctx: RequestContext, type: str, assessment_id: int, body) -> Any:
        return {"id": 321, "title": getattr(body, "title", "Section")}

    async def add_question(self, ctx: RequestContext, type: str, assessment_id: int,
                           section_id: int, body: QuestionCreate) -> Any:
        return {"id": 456, "questionType": body.questionType}

    async def create_announcement(self, ctx: RequestContext, body: AnnouncementCreate) -> Any:
        return {"id": 789, "title": body.title}

    async def update_announcement(self, ctx: RequestContext, announcement_id: int, body: AnnouncementUpdate) -> Any:
        return {"id": announcement_id}

    async def upload_file(self, ctx: RequestContext, files: dict,
                          entity_type: str | None = None, entity_id: int = 0,
                          best_effort: bool = False) -> list[ManagedFile]:
        return [ManagedFile(id=1, fileUrl="https://example.com/f.pdf",
                            filemime="application/pdf", filesize=1024, filename="f.pdf")]

    async def create_lecture(self, ctx: RequestContext, body: LectureCreate) -> Any:
        return {"id": 101, "title": body.title}

    async def attach_course_resource(self, ctx: RequestContext, entity_type: str,
                                     entity_id: int, resources: list[dict]) -> list[Any]:
        return [{"id": i + 1, **r} for i, r in enumerate(resources)]
