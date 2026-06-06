
import builtins

from ..contracts.context import RequestContext
from ..contracts.stores import Artifact, Message
from ..contracts.stores import ArtifactRegistry as IArtifactRegistry
from ..contracts.stores import SessionStore as ISessionStore


class InMemorySessionStore(ISessionStore):
    """In-memory SessionStore for unit tests and Dev B local development."""

    def __init__(self):
        self._transcripts: dict[tuple, list[Message]] = {}
        self._summaries: dict[tuple, str] = {}

    def _key(self, ctx: RequestContext) -> tuple:
        return (ctx.tenant_key, ctx.session_id)

    async def append_message(
        self, ctx: RequestContext, role: str, content: str, meta: dict | None = None
    ) -> None:
        key = self._key(ctx)
        self._transcripts.setdefault(key, []).append(Message(role=role, content=content, meta=meta))

    async def get_transcript(self, ctx: RequestContext, *, max_tokens: int) -> list[Message]:
        messages = self._transcripts.get(self._key(ctx), [])
        # Rough trim by character count.
        total = 0
        trimmed: list[Message] = []
        for msg in reversed(messages):
            token_est = len(msg.content) // 4
            if total + token_est > max_tokens and trimmed:
                break
            trimmed.append(msg)
            total += token_est
        return list(reversed(trimmed))

    async def set_summary(self, ctx: RequestContext, summary: str) -> None:
        self._summaries[self._key(ctx)] = summary

    async def get_summary(self, ctx: RequestContext) -> str | None:
        return self._summaries.get(self._key(ctx))


class InMemoryArtifactRegistry(IArtifactRegistry):
    """In-memory ArtifactRegistry for unit tests and Dev B local development."""

    def __init__(self):
        self._artifacts: dict[tuple, Artifact] = {}
        self._focus_stacks: dict[tuple, list[str]] = {}

    def _art_key(self, ctx: RequestContext, artifact_id: str) -> tuple:
        return (ctx.tenant_key, artifact_id)

    def _focus_key(self, ctx: RequestContext) -> tuple:
        return (ctx.tenant_key, ctx.session_id)

    async def add(self, ctx: RequestContext, art: Artifact) -> str:
        self._artifacts[self._art_key(ctx, art.id)] = art
        return art.id

    async def get(self, ctx: RequestContext, artifact_id: str) -> Artifact | None:
        return self._artifacts.get(self._art_key(ctx, artifact_id))

    async def update(self, ctx: RequestContext, artifact_id: str, patch: dict) -> Artifact:
        key = self._art_key(ctx, artifact_id)
        art = self._artifacts.get(key)
        if art is None:
            raise ValueError(f"Artifact {artifact_id} not found")
        updated = art.model_copy(update={**patch, "version": art.version + 1})
        self._artifacts[key] = updated
        return updated

    async def list(self, ctx: RequestContext, *, type: str | None = None) -> list[Artifact]:
        arts = [a for (tk, _), a in self._artifacts.items() if tk == ctx.tenant_key]
        if type:
            arts = [a for a in arts if a.type == type]
        return arts

    async def focus(self, ctx: RequestContext) -> builtins.list[str]:
        """Return top-of-focus-stack artifact IDs (most recently pushed first)."""
        return list(self._focus_stacks.get(self._focus_key(ctx), []))

    async def push_focus(self, ctx: RequestContext, artifact_id: str) -> None:
        key = self._focus_key(ctx)
        stack = self._focus_stacks.setdefault(key, [])
        if artifact_id in stack:
            stack.remove(artifact_id)
        stack.insert(0, artifact_id)
        self._focus_stacks[key] = stack[:10]
