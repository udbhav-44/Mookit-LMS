"""B3.5 — provenance stamping.

Every draft/commit is stamped "AI-generated · edited by instructor". Source citations are carried
through to the committed artifact's metadata.
"""

from __future__ import annotations

from typing import Any

PROVENANCE_LABEL = "AI-generated · edited by instructor"


def stamp(
    *,
    ai_generated: bool,
    edited_by_human: bool,
    source_ids: list[str],
    created_by: str | None = None,
) -> dict[str, Any]:
    return {
        "ai_generated": ai_generated,
        "edited_by_human": edited_by_human,
        "source_ids": list(source_ids),
        "created_by": created_by,
        "label": PROVENANCE_LABEL,
    }


def mark_edited(provenance: dict[str, Any]) -> dict[str, Any]:
    """Flip edited_by_human=True (used when a human edits a generated artifact)."""
    return {**provenance, "edited_by_human": True}
