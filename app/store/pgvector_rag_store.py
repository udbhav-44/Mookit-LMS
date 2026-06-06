"""pgvector RAG store (A2.5, production) — embeddings + cosine ANN retrieval in Postgres.

Drop-in for the keyword ``RAGStore``: same ``chunk_text`` / ``store_chunks`` / ``retrieve`` /
``save_metadata`` / ``delete_document`` / ``list_documents`` surface, so the worker and the orchestrator
use it unchanged. Tenant isolation is enforced by filtering every query on ``tenant_key`` — a
cross-tenant retrieve is structurally impossible.

Retrieval: embed the query, order chunks by cosine distance to the query vector, scoped to
(tenant_key, doc_id), limit k. Returns the same dict shape as the keyword store:
    {chunk_index, text, span, locator}
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select

from ..contracts.context import RequestContext
from .db import DocChunk
from .embeddings import OpenAIEmbedder
from .rag_store import RAGStore


class PgVectorRAGStore:
    def __init__(self, session_factory, embedder: OpenAIEmbedder) -> None:
        self.session_factory = session_factory
        self.embedder = embedder

    # Reuse the proven paragraph chunker.
    @staticmethod
    def chunk_text(text: str) -> list[dict[str, Any]]:
        return RAGStore.chunk_text(text)

    async def store_chunks(
        self, ctx: RequestContext, doc_artifact_id: str, chunks: list[dict[str, Any]]
    ) -> None:
        if not chunks:
            return
        vectors = await self.embedder.embed([c["text"] for c in chunks])
        async with self.session_factory() as session:
            # Replace any existing chunks for this (tenant, doc).
            await session.execute(
                delete(DocChunk).where(
                    DocChunk.tenant_key == ctx.tenant_key, DocChunk.doc_id == doc_artifact_id
                )
            )
            for chunk, vec in zip(chunks, vectors, strict=False):
                session.add(
                    DocChunk(
                        tenant_key=ctx.tenant_key,
                        doc_id=doc_artifact_id,
                        chunk_index=chunk.get("chunk_index", 0),
                        text=chunk["text"],
                        span=chunk.get("span", {}),
                        locator=chunk.get("locator", {}),
                        embedding=vec,
                    )
                )
            await session.commit()

    async def save_metadata(self, ctx: RequestContext, doc_artifact_id: str, metadata: dict) -> None:
        # Metadata lives on the artifact/FileMeta rows; chunks are self-describing. No-op for parity.
        return None

    async def retrieve(
        self, ctx: RequestContext, doc_artifact_id: str, query: str, k: int = 5
    ) -> list[dict[str, Any]]:
        qvec = await self.embedder.embed_one(query or "")
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(DocChunk)
                    .where(
                        DocChunk.tenant_key == ctx.tenant_key,
                        DocChunk.doc_id == doc_artifact_id,
                    )
                    .order_by(DocChunk.embedding.cosine_distance(qvec))
                    .limit(k)
                )
            ).scalars().all()
        return [
            {
                "chunk_index": r.chunk_index,
                "text": r.text,
                "span": r.span,
                "locator": r.locator,
            }
            for r in rows
        ]

    async def list_documents(self, ctx: RequestContext) -> list[str]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(DocChunk.doc_id).where(DocChunk.tenant_key == ctx.tenant_key).distinct()
                )
            ).scalars().all()
        return list(rows)

    async def delete_document(self, ctx: RequestContext, doc_artifact_id: str) -> None:
        async with self.session_factory() as session:
            await session.execute(
                delete(DocChunk).where(
                    DocChunk.tenant_key == ctx.tenant_key, DocChunk.doc_id == doc_artifact_id
                )
            )
            await session.commit()
