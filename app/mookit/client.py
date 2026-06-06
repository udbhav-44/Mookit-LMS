import logging
import time
from typing import Any, Callable, List, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
    before_sleep_log,
)

from ..contracts.mookit import MooKitClient as IMooKitClient
from ..contracts.context import RequestContext, PermissionMatrix
from .schemas import (
    AssessmentCreate, QuestionCreate, AnnouncementCreate, AnnouncementUpdate,
    LectureCreate, TaxonomyTerm, ManagedFile, UserMe,
    CourseResourceCreate,
)
from .errors import (
    MooKitError, MooKitRateLimitError, MooKitServerError,
    CircuitOpenError, map_http_error,
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

    async def call(self, coro):
        self._transition()
        if self._state == "open":
            raise CircuitOpenError("mooKIT")
        try:
            result = await coro
            self.record_success()
            return result
        except (MooKitRateLimitError, MooKitServerError, httpx.HTTPError):
            self.record_failure()
            raise
        except Exception:
            # Non-retryable errors (auth, 404) don't trip the breaker
            raise


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, (MooKitRateLimitError, MooKitServerError, httpx.ConnectError,
                            httpx.ReadTimeout, httpx.WriteTimeout))


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
    ) -> Any:
        """Send a request to mooKIT, unwrap the envelope, raise typed errors."""
        base_url = self._base_url_resolver(ctx.instance_id)
        url = f"{base_url}{path}"
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
            except Exception:
                raise MooKitServerError(f"Non-JSON response ({resp.status_code})", code=resp.status_code)

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

        return await self._breaker.call(_request())

    # ------------------------------------------------------------------
    # Users / Permissions / Taxonomy
    # ------------------------------------------------------------------

    async def users_me(self, ctx: RequestContext) -> UserMe:
        data = await self.call(ctx, "GET", "/users/me")
        return UserMe.model_validate(data)

    async def get_permissions(self, ctx: RequestContext) -> PermissionMatrix:
        data = await self.call(ctx, "GET", "/user_permissions/allowed")
        # API returns the resource map directly at the data level
        if isinstance(data, dict):
            return PermissionMatrix(resources=data)
        return PermissionMatrix(resources={})

    async def list_taxonomy(self, ctx: RequestContext, type: str) -> List[TaxonomyTerm]:
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
        return await self.call(ctx, "POST", "/announcements/add", json=body.model_dump(exclude_none=True))

    async def update_announcement(self, ctx: RequestContext, announcement_id: int, body: AnnouncementUpdate) -> Any:
        return await self.call(
            ctx, "PUT", f"/announcements/edit/{announcement_id}",
            json=body.model_dump(exclude_none=True),
        )

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    async def upload_file(
        self,
        ctx: RequestContext,
        files: dict,
        entity_type: Optional[str] = None,
        entity_id: int = 0,
    ) -> List[ManagedFile]:
        params: dict = {}
        if entity_type:
            params["entityType"] = entity_type
        if entity_id:
            params["entityId"] = entity_id
        data = await self.call(ctx, "POST", "/files/add", files=files, params=params)
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
        resources: List[dict],
    ) -> List[Any]:
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

    async def list_taxonomy(self, ctx: RequestContext, type: str) -> List[TaxonomyTerm]:
        return [TaxonomyTerm(id=1, name=f"{type.capitalize()} 1", type=type)]

    async def create_assessment(self, ctx: RequestContext, type: str, body: AssessmentCreate) -> Any:
        return {"id": 123, "type": type, "title": body.title}

    async def update_assessment(self, ctx: RequestContext, type: str, assessment_id: int, patch: dict) -> Any:
        return {"id": assessment_id, **patch}

    async def add_question(self, ctx: RequestContext, type: str, assessment_id: int,
                           section_id: int, body: QuestionCreate) -> Any:
        return {"id": 456, "questionType": body.questionType}

    async def create_announcement(self, ctx: RequestContext, body: AnnouncementCreate) -> Any:
        return {"id": 789, "title": body.title}

    async def update_announcement(self, ctx: RequestContext, announcement_id: int, body: AnnouncementUpdate) -> Any:
        return {"id": announcement_id}

    async def upload_file(self, ctx: RequestContext, files: dict,
                          entity_type: Optional[str] = None, entity_id: int = 0) -> List[ManagedFile]:
        return [ManagedFile(id=1, fileUrl="https://example.com/f.pdf",
                            filemime="application/pdf", filesize=1024, filename="f.pdf")]

    async def create_lecture(self, ctx: RequestContext, body: LectureCreate) -> Any:
        return {"id": 101, "title": body.title}

    async def attach_course_resource(self, ctx: RequestContext, entity_type: str,
                                     entity_id: int, resources: List[dict]) -> List[Any]:
        return [{"id": i + 1, **r} for i, r in enumerate(resources)]
