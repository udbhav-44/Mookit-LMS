from pydantic import BaseModel, Field
from typing import Any


class PermissionMatrix(BaseModel):
    """Cached result of GET /user_permissions/allowed.

    Shape matches the mooKIT API: { resourceName: [allowed_action, ...] }.
    Example: {"lectures": ["list", "create", "update", "delete"], "files": ["upload"]}
    """
    resources: dict[str, list[str]] = Field(default_factory=dict)

    def has_permission(self, resource: str, action: str) -> bool:
        return action in self.resources.get(resource, [])


class RequestContext(BaseModel):
    instance_id: str            # e.g. "hello.iitk.ac.in"  -> resolves to a mooKIT base URL
    course_id: str              # mooKIT "course" short-name (also the `course` header value)
    user_id: int                # mooKIT uid
    role: str = "instructor"    # role header value — informational; real authz uses PermissionMatrix
    session_id: str
    forwarded_headers: dict[str, str]   # {course, token, uid} — relayed to mooKIT, never logged raw
    permissions: PermissionMatrix       # cached result of GET /user_permissions/allowed
    tenant_key: str             # canonical "{instance_id}:{course_id}" — namespaces ALL storage/cache
    request_id: str             # correlation id, propagated through SSE + ARQ jobs
