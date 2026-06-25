"""Per-request Langfuse context propagation.

The orchestrator sets this once per chat turn so all downstream LLM calls
(including nested generator/comprehender calls) inherit the same tracing
attributes without threading request context through every function signature.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

from app.contracts import RequestContext


@dataclass(frozen=True)
class LangfuseContext:
    request_id: str
    session_id: str
    user_id: int
    tenant_key: str
    feature: str


_langfuse_ctx_var: ContextVar[LangfuseContext | None] = ContextVar(
    "langfuse_ctx", default=None
)


def get_langfuse_context() -> LangfuseContext | None:
    return _langfuse_ctx_var.get()


@contextmanager
def push_langfuse_context(ctx: RequestContext, *, feature: str) -> Iterator[None]:
    token = _langfuse_ctx_var.set(
        LangfuseContext(
            request_id=ctx.request_id,
            session_id=ctx.session_id,
            user_id=ctx.user_id,
            tenant_key=ctx.tenant_key,
            feature=feature,
        )
    )
    try:
        yield
    finally:
        _langfuse_ctx_var.reset(token)
