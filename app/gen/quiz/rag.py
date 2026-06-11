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

from app.contracts import RequestContext
from app.gen.quiz.schemas import Citation


class Evidence(BaseModel):
    span_id: str
    text: str
    locator: dict[str, Any]
    source_doc_id: str | None = None  # which uploaded_file artifact this span came from


class RetrieveFn(Protocol):
    async def __call__(
        self, ctx: RequestContext, doc_artifact_id: str, query: str, k: int
    ) -> list[Any]: ...


def _normalize_doc_ids(doc_artifact_id: str | list[str]) -> list[str]:
    if isinstance(doc_artifact_id, str):
        return [doc_artifact_id] if doc_artifact_id else []
    return [d for d in doc_artifact_id if d]


async def gather_evidence(
    retrieve: RetrieveFn,
    ctx: RequestContext,
    doc_artifact_id: str | list[str],
    *,
    topics: list[str] | None,
    k: int,
) -> list[Evidence]:
    """Pull relevant spans from one or more documents. Returns [] if nothing retrievable."""
    doc_ids = _normalize_doc_ids(doc_artifact_id)
    if not doc_ids:
        return []
    query = " ".join(topics) if topics else "key concepts and important facts"
    k_per = max(1, (k + len(doc_ids) - 1) // len(doc_ids))
    evidence: list[Evidence] = []
    for doc_id in doc_ids:
        spans = await retrieve(ctx, doc_id, query, k_per)
        for s in spans:
            ev = _to_evidence(s)
            evidence.append(ev.model_copy(update={"source_doc_id": doc_id}))
    return evidence[:k] if len(evidence) > k else evidence


def _to_evidence(s: Any) -> Evidence:
    """Normalise a retrieved span — either an object (test fake) or a dict (Dev A RAGStore)."""
    if isinstance(s, dict):
        span_id = str(s.get("span_id") or s.get("chunk_index") or "")
        text = s.get("text", "") or ""
        locator = dict(s.get("locator") or {})
        # RAGStore also carries a char span; fold it into the locator for citation fidelity.
        if "span" in s and isinstance(s["span"], dict):
            locator = {**s["span"], **locator}
        return Evidence(span_id=span_id, text=text, locator=locator)
    return Evidence(
        span_id=str(getattr(s, "span_id", "") or ""),
        text=getattr(s, "text", "") or "",
        locator=dict(getattr(s, "locator", {}) or {}),
    )


def citation_for(doc_artifact_id: str, evidence: Evidence) -> Citation:
    return Citation(source_id=doc_artifact_id, locator=evidence.locator, quote=evidence.text)
