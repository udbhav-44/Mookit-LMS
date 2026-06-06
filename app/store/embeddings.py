"""OpenAI embeddings client for RAG retrieval.

Produces dense vectors for document chunks (at index time) and queries (at retrieve time). Batched.
"""

from __future__ import annotations

from typing import Any

# text-embedding-3-small → 1536 dims; keep in sync with the DocChunk.embedding column.
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536


class OpenAIEmbedder:
    def __init__(self, client: Any, *, model: str = EMBED_MODEL, dim: int = EMBED_DIM) -> None:
        self._client = client
        self.model = model
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = await self._client.embeddings.create(model=self.model, input=texts)
        return [d.embedding for d in resp.data]

    async def embed_one(self, text: str) -> list[float]:
        out = await self.embed([text])
        return out[0] if out else [0.0] * self.dim
