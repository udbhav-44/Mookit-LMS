"""UK.3 — In-memory SessionStore + ArtifactRegistry.

Tenant-isolated by ``(tenant_key, session_id)``. ``update`` bumps ``version``. ``focus`` returns
most-recent-first. These stand in for Dev A's Redis+Postgres implementations.
"""

from __future__ import annotations

from typing import Any

from app.contracts import (
    Artifact,
    ArtifactRegistry,
    Message,
    RequestContext,
    SessionStore,
)


def _skey(ctx: RequestContext) -> tuple[str, str]:
    return (ctx.tenant_key, ctx.session_id)


class InMemorySessionStore(SessionStore):
    def __init__(self) -> None:
        self._messages: dict[tuple[str, str], list[Message]] = {}
        self._summary: dict[tuple[str, str], str] = {}

    async def append_message(
        self, ctx: RequestContext, role: str, content: str, meta: dict[str, Any] | None = None
    ) -> None:
        self._messages.setdefault(_skey(ctx), []).append(
            Message(role=role, content=content, meta=meta)
        )

    async def get_transcript(self, ctx: RequestContext, *, max_tokens: int) -> list[Message]:
        # The fake returns the full verbatim list; compaction logic lives in TranscriptManager.
        return list(self._messages.get(_skey(ctx), []))

    async def set_summary(self, ctx: RequestContext, summary: str) -> None:
        self._summary[_skey(ctx)] = summary

    async def get_summary(self, ctx: RequestContext) -> str | None:
        return self._summary.get(_skey(ctx))

    async def has_transcript(self, ctx: RequestContext) -> bool:
        return bool(self._messages.get(_skey(ctx)))

    async def replace_transcript(self, ctx: RequestContext, messages: list[Message]) -> None:
        self._messages[_skey(ctx)] = list(messages)


class InMemoryArtifactRegistry(ArtifactRegistry):
    def __init__(self) -> None:
        self._store: dict[tuple[str, str], dict[str, Artifact]] = {}
        self._focus: dict[tuple[str, str], list[str]] = {}
        self._counter = 0

    def _bucket(self, ctx: RequestContext) -> dict[str, Artifact]:
        return self._store.setdefault(_skey(ctx), {})

    async def add(self, ctx: RequestContext, art: Artifact) -> str:
        if not art.id:
            self._counter += 1
            art = art.model_copy(update={"id": f"art_{self._counter}"})
        if not art.namespaced_id:
            art = art.model_copy(
                update={"namespaced_id": f"{ctx.tenant_key}:{ctx.user_id}:{art.id}"}
            )
        self._bucket(ctx)[art.id] = art
        await self.push_focus(ctx, art.id)
        return art.id

    async def get(self, ctx: RequestContext, artifact_id: str) -> Artifact | None:
        return self._bucket(ctx).get(artifact_id)

    async def update(self, ctx: RequestContext, artifact_id: str, patch: dict[str, Any]) -> Artifact:
        bucket = self._bucket(ctx)
        current = bucket[artifact_id]
        merged = current.model_dump()
        # Shallow-merge top-level fields; payload patches merge one level deep.
        for k, v in patch.items():
            if k == "payload" and isinstance(v, dict):
                merged_payload = dict(merged.get("payload", {}))
                merged_payload.update(v)
                merged["payload"] = merged_payload
            else:
                merged[k] = v
        merged["version"] = current.version + 1
        updated = Artifact.model_validate(merged)
        bucket[artifact_id] = updated
        await self.push_focus(ctx, artifact_id)
        return updated

    async def list(self, ctx: RequestContext, *, type: str | None = None) -> list[Artifact]:
        items = list(self._bucket(ctx).values())
        if type is not None:
            items = [a for a in items if a.type == type]
        return items

    async def focus(self, ctx: RequestContext) -> list[str]:
        return list(self._focus.get(_skey(ctx), []))

    async def push_focus(self, ctx: RequestContext, artifact_id: str) -> None:
        stack = self._focus.setdefault(_skey(ctx), [])
        if artifact_id in stack:
            stack.remove(artifact_id)
        stack.insert(0, artifact_id)  # most-recent-first
