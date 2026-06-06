"""
ARQ worker (A1.6 / A2.6 / A3.5).

Tasks:
  extract_and_index_file  — sandboxed text extraction + RAG chunk storage
  create_questions_bulk   — idempotent batch question creation with progress events
  demo_task               — development smoke-test

Progress bridge:
  Every long-running task writes progress to Redis at:
      {tenant_key}:job:{job_id}:progress  →  JSON {"pct": int, "message": str, "status": str}

  The file-status endpoint (GET /v1/files/{file_id}/status) reads this key so the
  UI can poll without holding an SSE connection open during upload.

  For chat-inline progress (tool_progress SSE events), the orchestrator (Dev B) reads
  the same Redis key while streaming and emits tool_progress events.
"""

import json
import logging

import httpx
import redis.asyncio as aioredis
from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ..config import settings
from ..files.sandbox import ExtractionError, ExtractionSandbox
from ..store.db import FileMeta
from ..store.rag_store import RAGStore

logger = logging.getLogger(__name__)

# ── Progress helpers ──────────────────────────────────────────────────────────

async def _set_progress(redis, tenant_key: str, job_id: str, pct: int, message: str, status: str = "running") -> None:
    key = f"{tenant_key}:job:{job_id}:progress"
    await redis.set(key, json.dumps({"pct": pct, "message": message, "status": status}), ex=3600)


# ── Tasks ─────────────────────────────────────────────────────────────────────

async def extract_and_index_file(
    ctx: dict,
    *,
    tenant_key: str,
    file_id: str,
    file_path: str,
    job_id: str,
) -> dict:
    """Extract text from an uploaded file and store RAG chunks in Redis."""
    redis: aioredis.Redis = ctx["redis"]
    session_factory = ctx["session_factory"]

    await _set_progress(redis, tenant_key, job_id, 5, "Starting extraction…")

    # Update DB status.
    async with session_factory() as db:
        from sqlalchemy import update
        await db.execute(
            update(FileMeta)
            .where(FileMeta.id == file_id, FileMeta.tenant_key == tenant_key)
            .values(extraction_status="extracting")
        )
        await db.commit()

    try:
        sandbox = ExtractionSandbox()
        await _set_progress(redis, tenant_key, job_id, 20, "Extracting text…")
        text = await sandbox.extract_text(file_path)

    except ExtractionError as exc:
        logger.error("Extraction failed for file_id=%s: %s", file_id, exc)
        await _set_progress(redis, tenant_key, job_id, 0, f"Extraction failed: {exc}", status="failed")
        async with session_factory() as db:
            from sqlalchemy import update
            await db.execute(
                update(FileMeta)
                .where(FileMeta.id == file_id, FileMeta.tenant_key == tenant_key)
                .values(extraction_status="failed")
            )
            await db.commit()
        return {"status": "failed", "error": str(exc)}

    await _set_progress(redis, tenant_key, job_id, 60, "Chunking and indexing…")

    # Build a minimal context-like object for the RAGStore (only tenant_key needed).
    class _MinCtx:
        pass
    min_ctx = _MinCtx()
    min_ctx.tenant_key = tenant_key  # type: ignore[attr-defined]

    rag = RAGStore(redis)
    chunks = RAGStore.chunk_text(text)
    await rag.store_chunks(min_ctx, file_id, chunks)  # type: ignore[arg-type]
    await rag.save_metadata(min_ctx, file_id, {  # type: ignore[arg-type]
        "filename": file_path.split("/")[-1],
        "chunk_count": len(chunks),
        "char_count": len(text),
    })

    await _set_progress(redis, tenant_key, job_id, 100, f"Done — {len(chunks)} chunks indexed.", status="complete")

    async with session_factory() as db:
        from sqlalchemy import update
        await db.execute(
            update(FileMeta)
            .where(FileMeta.id == file_id, FileMeta.tenant_key == tenant_key)
            .values(extraction_status="indexed")
        )
        await db.commit()

    logger.info("File indexed: file_id=%s tenant=%s chunks=%d", file_id, tenant_key, len(chunks))
    return {"status": "complete", "chunks": len(chunks)}


async def create_questions_bulk(
    ctx: dict,
    *,
    tenant_key: str,
    job_id: str,
    assessment_type: str,
    assessment_id: int,
    section_id: int,
    questions: list,
    forwarded_headers: dict,
    instance_id: str,
) -> dict:
    """Idempotently create many questions with per-question progress events (A3.5).

    Uses an idempotency key per question: {tenant_key}:q_idem:{assessment_id}:{q_index}
    so a retry will skip already-created questions.
    """
    redis: aioredis.Redis = ctx["redis"]
    http: httpx.AsyncClient = ctx["http"]

    from ..contracts.context import PermissionMatrix, RequestContext
    from ..mookit.client import MooKitClient
    from ..mookit.schemas import QuestionCreate

    # Reconstruct a minimal RequestContext for the mooKIT client.
    req_ctx = RequestContext(
        instance_id=instance_id,
        course_id=forwarded_headers.get("course", ""),
        user_id=int(forwarded_headers.get("uid", 0)),
        role="instructor",
        session_id=job_id,
        forwarded_headers=forwarded_headers,
        permissions=PermissionMatrix(resources={}),
        tenant_key=tenant_key,
        request_id=job_id,
    )

    def _resolver(iid: str) -> str:
        return settings.mookit.base_url

    client = MooKitClient(http, _resolver)

    total = len(questions)
    created = 0
    skipped = 0

    await _set_progress(redis, tenant_key, job_id, 0, f"0/{total} questions created")

    for idx, q_data in enumerate(questions):
        idem_key = f"{tenant_key}:q_idem:{assessment_id}:{idx}"
        already_done = await redis.get(idem_key)
        if already_done:
            skipped += 1
            continue

        try:
            body = QuestionCreate(**q_data)
            await client.add_question(req_ctx, assessment_type, assessment_id, section_id, body)
            await redis.set(idem_key, "1", ex=86400)
            created += 1
        except Exception as exc:
            logger.warning("Question %d/%d failed: %s", idx + 1, total, exc)

        pct = int((idx + 1) / total * 100)
        await _set_progress(redis, tenant_key, job_id, pct, f"{created}/{total} questions created")

    await _set_progress(redis, tenant_key, job_id, 100,
                        f"Done — {created} created, {skipped} skipped.", status="complete")
    return {"created": created, "skipped": skipped, "total": total}


async def demo_task(ctx: dict, name: str) -> str:
    return f"Hello {name}"


# ── Worker lifecycle ──────────────────────────────────────────────────────────

async def startup(ctx: dict) -> None:
    ctx["redis"] = aioredis.from_url(settings.redis.url, decode_responses=True)
    ctx["http"] = httpx.AsyncClient(
        http2=True,
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0),
    )
    engine = create_async_engine(settings.db.url, pool_size=5, max_overflow=5)
    ctx["db_engine"] = engine
    ctx["session_factory"] = async_sessionmaker(engine, expire_on_commit=False)
    logger.info("ARQ worker started")


async def shutdown(ctx: dict) -> None:
    await ctx["redis"].aclose()
    await ctx["http"].aclose()
    await ctx["db_engine"].dispose()
    logger.info("ARQ worker stopped")


class WorkerSettings:
    functions = [extract_and_index_file, create_questions_bulk, demo_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis.url)
    max_jobs = 10
    job_timeout = 600   # 10 minutes max per job
