"""B3.3 — lecture metadata generation.

Resolves week/module labels to taxonomy ids via MooKitClient, and generates a lecture title (+ optional
description). Returns a structured draft; the title generator is an injected seam with a deterministic
default for offline testing.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from app.contracts import RequestContext
from app.contracts.mookit import MooKitClient


class LectureMeta(BaseModel):
    title: str
    description: str | None
    week_label: str
    week_id: int | None
    module_label: str | None
    topic_id: int | None
    file_artifact_id: str | None
    release_on: int | None  # unix seconds; None => publish now / draft
    ambiguous: bool = False
    candidates: list[dict] = []


class TitleFn(Protocol):
    async def __call__(self, *, file_artifact_id: str | None, week_label: str) -> str: ...


async def draft_lecture_meta(
    mookit: MooKitClient,
    ctx: RequestContext,
    *,
    week_label: str,
    module_label: str | None = None,
    file_artifact_id: str | None = None,
    release_on: int | None = None,
    title_generator: TitleFn | None = None,
) -> LectureMeta:
    week_id, week_ambiguous, week_candidates = await _resolve(mookit, ctx, "week", week_label)
    topic_id = None
    if module_label:
        topic_id, _amb, _cands = await _resolve(mookit, ctx, "module", module_label)

    if title_generator is not None:
        title = await title_generator(file_artifact_id=file_artifact_id, week_label=week_label)
    else:
        title = _default_title(week_label)

    return LectureMeta(
        title=title,
        description=None,
        week_label=week_label,
        week_id=week_id,
        module_label=module_label,
        topic_id=topic_id,
        file_artifact_id=file_artifact_id,
        release_on=release_on,
        ambiguous=week_ambiguous,
        candidates=week_candidates,
    )


async def _resolve(
    mookit: MooKitClient, ctx: RequestContext, type_: str, label: str
) -> tuple[int | None, bool, list[dict]]:
    terms = await mookit.list_taxonomy(ctx, type_)
    norm = " ".join(label.lower().split())
    exact = [t for t in terms if " ".join(t.name.lower().split()) == norm]
    candidates = [{"id": t.id, "title": t.name} for t in terms]
    if exact:
        return exact[0].id, False, candidates
    return None, True, candidates


def _default_title(week_label: str) -> str:
    return f"Lecture — {week_label}"
