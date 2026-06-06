"""Select the RAG backend: pgvector (production) or keyword/Redis (fallback/dev).

Both backends expose the same retrieve/store surface, so the orchestrator and worker are agnostic.
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import Settings
from .embeddings import OpenAIEmbedder
from .pgvector_rag_store import PgVectorRAGStore
from .rag_store import RAGStore

logger = logging.getLogger(__name__)


def make_rag_store(
    settings: Settings,
    *,
    redis: Any,
    session_factory: Any,
    openai_client: Any,
) -> Any:
    backend = settings.rag_backend
    if backend == "pgvector":
        if session_factory is None or openai_client is None:
            logger.warning("pgvector RAG requested but session_factory/openai_client missing; "
                           "falling back to keyword store.")
            return RAGStore(redis)
        embedder = OpenAIEmbedder(
            openai_client, model=settings.openai.embed_model, dim=settings.openai.embed_dim
        )
        return PgVectorRAGStore(session_factory, embedder)
    return RAGStore(redis)
