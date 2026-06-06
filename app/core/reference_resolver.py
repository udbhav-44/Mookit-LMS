"""B1.3 — reference resolution.

Resolves vague references ("it", "that quiz", "the announcement") against the artifact registry using a
focus stack (recency × type-match) — not coreference NLP. Injects a compact artifact manifest into
context each turn. On ambiguity (tie / low confidence) it asks for confirmation rather than guessing.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.contracts import ArtifactRegistry, RequestContext

# Phrase → artifact type hints. Used to bias resolution toward the referenced kind.
_TYPE_HINTS: dict[str, str] = {
    "quiz": "assessment_draft",
    "assessment": "assessment_draft",
    "exam": "assessment_draft",
    "assignment": "assessment_draft",
    "questions": "assessment_draft",
    "announcement": "announcement_draft",
    "message": "announcement_draft",
    "notice": "announcement_draft",
    "lecture": "lecture_draft",
    "video": "lecture_draft",
    "file": "uploaded_file",
    "document": "uploaded_file",
    "pdf": "uploaded_file",
}


class Resolution(BaseModel):
    artifact_id: str | None = None
    confidence: float = 0.0
    candidates: list[dict] = []
    needs_confirmation: bool = False
    confirm_prompt: str | None = None


class ReferenceResolver:
    def __init__(self, registry: ArtifactRegistry) -> None:
        self._registry = registry

    async def manifest(self, ctx: RequestContext) -> str:
        """Compact, recent-first manifest of artifacts: id · title · type · status · v."""
        focus = await self._registry.focus(ctx)
        artifacts = {a.id: a for a in await self._registry.list(ctx)}
        ordered = [artifacts[i] for i in focus if i in artifacts]
        # Include any not-yet-focused artifacts at the end.
        ordered += [a for a in artifacts.values() if a.id not in set(focus)]
        if not ordered:
            return "(no artifacts yet)"
        lines = [
            f"- {a.id} · \"{a.title}\" · {a.type} · {a.status} · v{a.version}" for a in ordered
        ]
        return "\n".join(lines)

    async def resolve(
        self, ctx: RequestContext, phrase: str, *, expected_type: str | None = None
    ) -> Resolution:
        focus = await self._registry.focus(ctx)
        artifacts = {a.id: a for a in await self._registry.list(ctx)}
        ordered = [artifacts[i] for i in focus if i in artifacts]

        wanted_type = expected_type or _infer_type(phrase)
        # Score each artifact: type match dominates, recency breaks ties.
        scored: list[tuple[float, object]] = []
        for rank, art in enumerate(ordered):
            recency = 1.0 - (rank / max(len(ordered), 1))
            type_match = 1.0 if (wanted_type and art.type == wanted_type) else 0.0
            score = type_match * 10 + recency
            scored.append((score, art))
        scored.sort(key=lambda t: t[0], reverse=True)

        if not scored:
            return Resolution(needs_confirmation=False, confirm_prompt="No artifacts exist yet.")

        candidates_of_type = (
            [a for a in ordered if a.type == wanted_type] if wanted_type else ordered
        )

        # Ambiguity: more than one candidate of the wanted type ⇒ confirm.
        if wanted_type and len(candidates_of_type) > 1:
            top = candidates_of_type[0]
            return Resolution(
                artifact_id=None,
                confidence=0.4,
                candidates=[{"id": a.id, "title": a.title} for a in candidates_of_type],
                needs_confirmation=True,
                confirm_prompt=(
                    f"You have {len(candidates_of_type)} {wanted_type.replace('_', ' ')}s. "
                    f"Did you mean '{top.title}'?"
                ),
            )

        # Type mismatch: wanted a type but none of that type exist ⇒ no false match.
        if wanted_type and not candidates_of_type:
            return Resolution(
                artifact_id=None,
                confidence=0.0,
                candidates=[{"id": a.id, "title": a.title} for a in ordered],
                needs_confirmation=True,
                confirm_prompt=f"I don't see a {wanted_type.replace('_', ' ')} to act on.",
            )

        best_art = scored[0][1]
        return Resolution(
            artifact_id=best_art.id,  # type: ignore[attr-defined]
            confidence=0.9,
            candidates=[{"id": best_art.id, "title": best_art.title}],  # type: ignore[attr-defined]
            needs_confirmation=False,
        )


def _infer_type(phrase: str) -> str | None:
    low = phrase.lower()
    for keyword, art_type in _TYPE_HINTS.items():
        if keyword in low:
            return art_type
    return None
