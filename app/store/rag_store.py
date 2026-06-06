"""
RAG store (A2.5) — tenant-namespaced per-document chunk storage with keyword retrieval.

Chunks are stored in Redis as a JSON list under:
    rag:{tenant_key}:{doc_artifact_id}:chunks

Each chunk dict:
    {
        "chunk_index": int,
        "text": str,
        "span": {"start": int, "end": int},   # character offsets in the extracted text
        "locator": {"page": int, "para": int}, # best-effort structural locator
    }

retrieve() returns the top-k chunks ranked by a simple term-overlap score.
Authorization is enforced by always scoping keys to tenant_key — a cross-tenant
retrieve is structurally impossible.

For production: replace the Redis list with pgvector embeddings; the interface
(retrieve signature and return shape) is stable and Dev B does not need to change.
"""

import json
import re
import logging
from typing import List, Dict, Any

import redis.asyncio as aioredis

from ..contracts.context import RequestContext

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 512     # target chunk size in characters
_CHUNK_OVERLAP = 64   # overlap between adjacent chunks


class RAGStore:
    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client

    # ------------------------------------------------------------------
    # Keys
    # ------------------------------------------------------------------

    def _chunks_key(self, tenant_key: str, doc_id: str) -> str:
        return f"rag:{tenant_key}:{doc_id}:chunks"

    def _meta_key(self, tenant_key: str, doc_id: str) -> str:
        return f"rag:{tenant_key}:{doc_id}:meta"

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    @staticmethod
    def chunk_text(text: str) -> List[Dict[str, Any]]:
        """Split `text` into overlapping chunks and return chunk dicts."""
        chunks: List[Dict[str, Any]] = []
        start = 0
        chunk_index = 0

        # Split on paragraph boundaries first, then hard-cut if necessary.
        paragraphs = re.split(r"\n{2,}", text)
        buf = ""
        buf_start = 0

        char_pos = 0
        for para in paragraphs:
            if len(buf) + len(para) > _CHUNK_SIZE and buf:
                chunks.append({
                    "chunk_index": chunk_index,
                    "text": buf.strip(),
                    "span": {"start": buf_start, "end": buf_start + len(buf)},
                    "locator": {"para": chunk_index},
                })
                chunk_index += 1
                # overlap: keep last _CHUNK_OVERLAP chars
                overlap_start = max(0, len(buf) - _CHUNK_OVERLAP)
                buf = buf[overlap_start:]
                buf_start = buf_start + overlap_start

            buf += para + "\n\n"
            char_pos += len(para) + 2

        if buf.strip():
            chunks.append({
                "chunk_index": chunk_index,
                "text": buf.strip(),
                "span": {"start": buf_start, "end": buf_start + len(buf)},
                "locator": {"para": chunk_index},
            })

        return chunks

    async def store_chunks(
        self, ctx: RequestContext, doc_artifact_id: str, chunks: List[Dict[str, Any]]
    ) -> None:
        """Persist `chunks` for document `doc_artifact_id` under this tenant."""
        key = self._chunks_key(ctx.tenant_key, doc_artifact_id)
        pipe = self.redis.pipeline()
        pipe.delete(key)
        for chunk in chunks:
            pipe.rpush(key, json.dumps(chunk))
        pipe.expire(key, 7 * 86400)  # 1 week TTL
        await pipe.execute()

    async def save_metadata(self, ctx: RequestContext, doc_artifact_id: str, metadata: Dict[str, Any]) -> None:
        key = self._meta_key(ctx.tenant_key, doc_artifact_id)
        await self.redis.hset(key, mapping={k: str(v) for k, v in metadata.items()})
        await self.redis.expire(key, 7 * 86400)

    # ------------------------------------------------------------------
    # Retrieval (Contract: retrieve(ctx, doc_artifact_id, query, k))
    # ------------------------------------------------------------------

    async def retrieve(
        self, ctx: RequestContext, doc_artifact_id: str, query: str, k: int = 5
    ) -> List[Dict[str, Any]]:
        """Return up to k chunks most relevant to `query`.

        Enforces tenant isolation: key is scoped to ctx.tenant_key so a cross-tenant
        retrieve always returns an empty list for the wrong tenant.

        Scoring: term-overlap ratio (sum of query-word hits / query-word count).
        Replace with embedding cosine similarity when pgvector is available.
        """
        key = self._chunks_key(ctx.tenant_key, doc_artifact_id)
        raw = await self.redis.lrange(key, 0, -1)
        if not raw:
            return []

        chunks = [json.loads(r) for r in raw]
        query_words = set(re.findall(r"\w+", query.lower()))

        scored: List[tuple[float, Dict[str, Any]]] = []
        for chunk in chunks:
            text_words = set(re.findall(r"\w+", chunk["text"].lower()))
            if query_words:
                score = len(query_words & text_words) / len(query_words)
            else:
                score = 0.0
            scored.append((score, chunk))

        scored.sort(key=lambda x: -x[0])
        return [c for _, c in scored[:k]]

    async def list_documents(self, ctx: RequestContext) -> List[str]:
        """List all document IDs indexed under this tenant."""
        pattern = f"rag:{ctx.tenant_key}:*:chunks"
        keys = await self.redis.keys(pattern)
        doc_ids = []
        for k in keys:
            key_str = k if isinstance(k, str) else k.decode()
            parts = key_str.split(":")
            # Pattern: rag:{tenant_key}:{doc_id}:chunks — doc_id is everything between
            if len(parts) >= 4:
                doc_ids.append(parts[-2])
        return doc_ids

    async def delete_document(self, ctx: RequestContext, doc_artifact_id: str) -> None:
        pipe = self.redis.pipeline()
        pipe.delete(self._chunks_key(ctx.tenant_key, doc_artifact_id))
        pipe.delete(self._meta_key(ctx.tenant_key, doc_artifact_id))
        await pipe.execute()
