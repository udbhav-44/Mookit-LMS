from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TenantMixin:
    """All tables that hold tenant-scoped data must include tenant_key."""
    tenant_key: Mapped[str] = mapped_column(String(255), index=True, nullable=False)


class Session(Base, TenantMixin):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # Human-readable label for the chat-history list (derived from the first user message).
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    # Bumped on every turn so the history list can sort most-recent-first.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_sessions_tenant_user_updated", "tenant_key", "user_id", "updated_at"),
    )


class Message(Base, TenantMixin):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class Artifact(Base, TenantMixin):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    provenance: Mapped[dict] = mapped_column(JSON, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # Which chat session produced this artifact (nullable: pre-existing rows + non-chat creation).
    session_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class AuditLog(Base, TenantMixin):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    tool: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class PendingAction(Base, TenantMixin):
    __tablename__ = "pending_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target_ref: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # sha256 hex of canonical payload
    confirm_token: Mapped[str] = mapped_column(String(64), nullable=False)  # secrets.token_urlsafe(32), one-time
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)  # pending|confirmed|rejected
    preview_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)   # PreviewRender for the UI
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class FileMeta(Base, TenantMixin):
    __tablename__ = "file_meta"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    filesize: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)  # server-side path, never exposed
    extraction_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    # pending | extracting | indexed | failed
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # ARQ job ID for progress polling
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # Which chat session this upload belongs to (nullable: pre-existing rows + non-chat uploads).
    session_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class InstanceRegistry(Base):
    """Maps instance_id → mooKIT base URL + per-instance config. Not tenant-scoped (global)."""
    __tablename__ = "instance_registry"

    instance_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # config can hold: model override, limits override, retention policy, etc.


# pgvector column for RAG embeddings. The `vector` extension must exist (migration creates it).
from pgvector.sqlalchemy import Vector  # noqa: E402

from .embeddings import EMBED_DIM  # noqa: E402


class DocChunk(Base, TenantMixin):
    """A retrievable, embedded chunk of an uploaded document (RAG store; pgvector backend)."""
    __tablename__ = "doc_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    span: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)      # {start,end} char offsets
    locator: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)   # {page,para}
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
