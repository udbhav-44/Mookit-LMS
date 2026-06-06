"""B2.1 — RAG-grounded evidence gathering + citation construction.

Generation is strictly grounded in retrieved evidence. ``gather_evidence`` pulls spans via Dev A's
``retrieve`` seam; ``citation_for`` turns a span into the Citation attached to every question. No
evidence ⇒ no questions (the caller must not fabricate ungrounded items).

The ``retrieve`` callable is injected (Protocol) so this works against the fake RAG solo and the real
index later.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel

from app.contracts.types import RequestContext
from app.gen.quiz.schemas import Citation


class Evidence(BaseModel):
    span_id: str
    text: str
    locator: dict[str, Any]


class RetrieveFn(Protocol):
    async def __call__(
        self, ctx: RequestContext, doc_artifact_id: str, query: str, k: int
    ) -> list[Any]: ...


async def gather_evidence(
    retrieve: RetrieveFn,
    ctx: RequestContext,
    doc_artifact_id: str,
    *,
    topics: list[str] | None,
    k: int,
) -> list[Evidence]:
    """Pull relevant spans. Returns [] if nothing retrievable (caller must not hallucinate)."""
    query = " ".join(topics) if topics else ""
    spans = await retrieve(ctx, doc_artifact_id, query, k)
    evidence: list[Evidence] = []
    for s in spans:
        evidence.append(
            Evidence(
                span_id=getattr(s, "span_id", "") or "",
                text=getattr(s, "text", "") or "",
                locator=dict(getattr(s, "locator", {}) or {}),
            )
        )
    return evidence


def citation_for(doc_artifact_id: str, evidence: Evidence) -> Citation:
    return Citation(source_id=doc_artifact_id, locator=evidence.locator, quote=evidence.text)
