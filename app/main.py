"""
Application entry point and component wiring (A0.4 / A1.4).

lifespan() creates every shared resource once and stores it on app.state so all
request handlers access the same pool/client via Depends(...).

app.state:
    http_client      httpx.AsyncClient      — shared HTTP/2 connection pool
    redis            Redis                  — async Redis pool
    db_engine        AsyncEngine            — SQLAlchemy engine
    session_factory  async_sessionmaker     — DB session factory
    arq_pool         ArqRedis               — ARQ job queue
    mookit_client    MooKitClient           — typed mooKIT API client
    session_store    RedisSessionStore      — transcript + summary store
    artifact_registry DurableArtifactRegistry
    rag_store        RAGStore
    audit_logger     AuditLogger
    orchestrator     None                   — Dev B sets this to their Orchestrator impl

Graceful shutdown:
    On SIGTERM the lifespan finally-block closes all connections.
    Uvicorn is configured with --timeout-graceful-shutdown so in-flight SSE streams
    complete or time out before the process exits.
"""

import logging
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .api import chat, confirm, files, health, meta, quiz, sessions
from .audit.logger import AuditLogger
from .config import settings
from .mookit.client import MooKitClient
from .obs.logging import setup_logging
from .obs.tracing import init_langfuse, init_otel
from .store.durable_artifact_registry import DurableArtifactRegistry
from .store.redis_store import RedisSessionStore

setup_logging()
logger = logging.getLogger(__name__)


# ── Instance registry (A4.6) — in-memory cache of instance_id → base_url ────

_instance_url_cache: dict[str, str] = {}


def _make_base_url_resolver(session_factory, default_base_url: str):
    """Return a callable that resolves instance_id → mooKIT base URL.

    Looks up the instance_registry table and caches hits in-process.
    Falls back to `default_base_url` (from settings) if the instance is not registered.
    """
    async def _resolve_async(instance_id: str) -> str:
        if instance_id in _instance_url_cache:
            return _instance_url_cache[instance_id]
        try:
            from sqlalchemy import select

            from .store.db import InstanceRegistry
            async with session_factory() as db:
                result = await db.execute(
                    select(InstanceRegistry).where(InstanceRegistry.instance_id == instance_id)
                )
                row = result.scalar_one_or_none()
            if row:
                _instance_url_cache[instance_id] = row.base_url
                return row.base_url
        except Exception as exc:
            logger.warning("Instance registry lookup failed for %s: %s", instance_id, exc)
        return default_base_url

    # MooKitClient.call() is async, so it will await this resolver.
    # We wrap it to make the signature synchronous-looking but still async.
    def resolver(instance_id: str) -> str:
        # Called inside an async context (within MooKitClient.call).
        # Return default synchronously; the async version is used for the warm path.
        return _instance_url_cache.get(instance_id, default_base_url)

    return resolver


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting mooKIT AI Assistant service…")

    # 1. Shared HTTP client (HTTP/2 connection pool, per A0.4 spec).
    app.state.http_client = httpx.AsyncClient(
        http2=True,
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
        timeout=httpx.Timeout(
            connect=settings.mookit.timeout_connect,
            read=settings.mookit.timeout_read,
            write=settings.mookit.timeout_write,
            pool=settings.mookit.timeout_pool,
        ),
    )

    # 2. Redis pool.
    app.state.redis = aioredis.from_url(settings.redis.url, decode_responses=True)

    # 3. Database engine + session factory.
    app.state.db_engine = create_async_engine(
        settings.db.url,
        pool_size=settings.db.pool_size,
        max_overflow=settings.db.max_overflow,
        echo=settings.debug,
    )
    app.state.session_factory = async_sessionmaker(
        app.state.db_engine, expire_on_commit=False
    )

    # Create tables if absent (idempotent) so the stack runs out-of-the-box. In production set
    # AUTO_CREATE_TABLES=false and run `alembic upgrade head`.
    if settings.auto_create_tables:
        from sqlalchemy import text

        from .store.db import Base
        try:
            async with app.state.db_engine.begin() as conn:
                # pgvector extension for the doc_chunks embedding column.
                try:
                    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                except Exception as exc:
                    logger.warning("Could not ensure pgvector extension: %s", exc)
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database schema ensured.")
        except Exception as exc:
            logger.warning("DB schema init skipped/failed: %s", exc)

    # 4. ARQ job queue.
    try:
        app.state.arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis.url))
        logger.info("ARQ pool connected")
    except Exception as exc:
        logger.warning("ARQ pool unavailable (background jobs disabled): %s", exc)
        app.state.arq_pool = None

    # 5. mooKIT client with circuit breaker.
    base_url_resolver = _make_base_url_resolver(
        app.state.session_factory, settings.mookit.base_url
    )
    app.state.mookit_client = MooKitClient(
        http=app.state.http_client,
        base_url_resolver=base_url_resolver,
        fail_max=settings.mookit.circuit_breaker_fail_max,
        reset_seconds=settings.mookit.circuit_breaker_reset_seconds,
    )

    # 6. Session store (Redis-backed).
    app.state.session_store = RedisSessionStore(app.state.redis)

    # 7. Artifact registry (Redis hot + Postgres durable).
    app.state.artifact_registry = DurableArtifactRegistry(
        session_factory=app.state.session_factory,
        redis=app.state.redis,
    )

    # 8. Shared OpenAI client + RAG store (pgvector embeddings, or keyword fallback).
    from openai import AsyncOpenAI

    from .store.rag_factory import make_rag_store
    app.state.openai_client = AsyncOpenAI(api_key=settings.openai.api_key.get_secret_value())
    app.state.rag_store = make_rag_store(
        settings,
        redis=app.state.redis,
        session_factory=app.state.session_factory,
        openai_client=app.state.openai_client,
    )

    # 9. Audit logger.
    app.state.audit_logger = AuditLogger(app.state.session_factory)

    # 10. Orchestrator seam — Dev B's AI brain wired onto the platform resources above.
    try:
        from .core.wiring import build_orchestrator
        app.state.orchestrator = build_orchestrator(
            settings=settings,
            mookit_client=app.state.mookit_client,
            session_store=app.state.session_store,
            artifact_registry=app.state.artifact_registry,
            rag_store=app.state.rag_store,
            session_factory=app.state.session_factory,
            openai_client=app.state.openai_client,
        )
        logger.info("Orchestrator (AI brain) wired.")
    except Exception as exc:
        logger.warning("Orchestrator wiring failed (chat will use stub): %s", exc)
        app.state.orchestrator = None

    # 11. Observability.
    init_langfuse()
    init_otel()

    logger.info("mooKIT AI Assistant service ready.")
    yield

    # ── Graceful shutdown ────────────────────────────────────────────────────
    logger.info("Shutting down mooKIT AI Assistant service…")
    if app.state.arq_pool:
        await app.state.arq_pool.aclose()
    await app.state.http_client.aclose()
    await app.state.redis.aclose()
    await app.state.db_engine.dispose()
    logger.info("Shutdown complete.")


# ── App factory ───────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.security.allowed_origins,  # lock to mooKIT frontend origins in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _service_key_guard(request: Request, call_next):
    """Trust boundary: if SECURITY__SERVICE_API_KEY is set, require a matching x-service-key header.

    Health checks, docs, and the sample UI are exempt so probes and demos still work.
    """
    import secrets as _secrets

    expected = settings.security.service_api_key.get_secret_value()
    path = request.url.path
    exempt = path.startswith(("/health", "/docs", "/redoc", "/openapi", "/ui")) or path == "/"
    if expected and not exempt:
        provided = request.headers.get("x-service-key", "")
        if not _secrets.compare_digest(provided, expected):
            return JSONResponse(status_code=401, content={"success": False,
                                "error": {"code": 401, "message": "Invalid or missing service key"}})
    return await call_next(request)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(health.router,   prefix="/health",      tags=["health"])
app.include_router(chat.router,     prefix="/v1",          tags=["chat"])
app.include_router(sessions.router, prefix="/v1/sessions", tags=["sessions"])
app.include_router(files.router,    prefix="/v1",          tags=["files"])
app.include_router(quiz.router,     prefix="/v1",          tags=["quiz"])
app.include_router(confirm.router,  prefix="/v1",          tags=["confirm"])
app.include_router(meta.router,     prefix="/v1",          tags=["meta"])

# ── Sample UI (static) ────────────────────────────────────────────────────────
# Served at /ui for local demos; the production chat UI is built by the mooKIT frontend team.
import os as _os  # noqa: E402

from fastapi.staticfiles import StaticFiles  # noqa: E402

_ui_dir = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "sample-ui")
if _os.path.isdir(_ui_dir):
    app.mount("/ui", StaticFiles(directory=_ui_dir, html=True), name="sample-ui")

# ── Global exception handler ──────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": {"code": 500, "message": "Internal server error"}},
    )
