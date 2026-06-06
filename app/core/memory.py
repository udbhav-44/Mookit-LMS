"""B1.2 — two-channel memory.

Channel 1 (transcript): recent N turns verbatim + a running summary of older turns. Compaction is
triggered on a token threshold; stale tool-output dumps are condensed first. Artifact payloads are
NEVER stored here.

Channel 2 (artifacts): mutations ("add 5 more", "make harder") are operations that bump an artifact's
``version`` in the registry — never appended as prose. The draft therefore survives transcript
compaction because it lives in structured state.
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


def estimate_tokens(messages: list[Message]) -> int:
    """Cheap token estimate (~4 chars/token). Good enough to trigger compaction deterministically."""
    chars = sum(len(m.content) for m in messages)
    return (chars + 3) // 4


class TranscriptManager:
    """Buffer + summary hybrid over a SessionStore."""

    def __init__(
        self,
        store: SessionStore,
        *,
        max_tokens: int,
        keep_recent: int,
        summarize: Any | None = None,
    ) -> None:
        self._store = store
        self._max_tokens = max_tokens
        self._keep_recent = keep_recent
        # summarize: optional async callable (messages) -> str. Defaults to a deterministic stub so
        # memory is fully testable offline; the LLM-backed summarizer is injected in integration.
        self._summarize = summarize or _default_summarize

    async def view(self, ctx: RequestContext, *, max_tokens: int | None = None) -> list[Message]:
        """Return the compacted transcript: [summary message?] + recent verbatim turns."""
        budget = max_tokens if max_tokens is not None else self._max_tokens
        messages = await self._store.get_transcript(ctx, max_tokens=budget)
        summary = await self._store.get_summary(ctx)
        recent = messages[-self._keep_recent :] if self._keep_recent else messages
        view: list[Message] = []
        if summary:
            view.append(Message(role="developer", content=f"Conversation so far (summary): {summary}"))
        view.extend(recent)
        return view

    async def maybe_compact(self, ctx: RequestContext) -> bool:
        """If over the token threshold, summarize older turns into the summary slot. Returns True if compacted."""
        messages = await self._store.get_transcript(ctx, max_tokens=self._max_tokens)
        if estimate_tokens(messages) <= self._max_tokens or len(messages) <= self._keep_recent:
            return False
        older = messages[: -self._keep_recent] if self._keep_recent else messages
        condensed = [_condense_tool_dump(m) for m in older]
        prior = await self._store.get_summary(ctx)
        summary = await self._summarize(condensed, prior)
        await self._store.set_summary(ctx, summary)
        return True


def _condense_tool_dump(m: Message) -> Message:
    """Shrink large tool-output messages early so they don't dominate the summary."""
    if m.role == "tool" and len(m.content) > 240:
        return Message(role=m.role, content=m.content[:240] + " …[tool output truncated]")
    return m


async def _default_summarize(messages: list[Message], prior: str | None) -> str:
    """Deterministic offline summarizer: lists the roles + first words of each older turn."""
    parts = [prior] if prior else []
    for m in messages:
        snippet = m.content.strip().split("\n", 1)[0][:60]
        parts.append(f"{m.role}: {snippet}")
    return " | ".join(p for p in parts if p)


async def apply_operation(
    registry: ArtifactRegistry,
    ctx: RequestContext,
    artifact_id: str,
    patch: dict[str, Any],
) -> Artifact:
    """Apply a structured mutation to an artifact (bumps version). Never writes prose to the transcript."""
    return await registry.update(ctx, artifact_id, patch)
