"""durable chat history + per-session scoping

Adds the columns/indexes that make chat history and per-chat context real:
  - sessions.title, sessions.updated_at (+ composite index for the history list)
  - file_meta.session_id (+ index)
  - artifacts.session_id (+ index)

Convergence note: ``0001_initial`` builds the schema via ``Base.metadata.create_all``, which only
CREATEs missing tables and never ALTERs existing ones. So on a fresh DB these columns already exist
(create_all sees them on the models) and this migration is effectively a no-op guarded by
``IF NOT EXISTS``; on a DB created before this change, the explicit ``add_column`` calls below bring
it up to date. Keeping both paths in sync is intentional.

Revision ID: 0002_session_history
Revises: 0001_initial
Create Date: 2026-06-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_session_history"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    def _columns(table: str) -> set[str]:
        try:
            return {c["name"] for c in insp.get_columns(table)}
        except Exception:
            return set()

    def _indexes(table: str) -> set[str]:
        try:
            return {i["name"] for i in insp.get_indexes(table)}
        except Exception:
            return set()

    sess_cols = _columns("sessions")
    if "title" not in sess_cols:
        op.add_column("sessions", sa.Column("title", sa.String(length=512), nullable=True))
    if "updated_at" not in sess_cols:
        op.add_column(
            "sessions",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )

    if "session_id" not in _columns("file_meta"):
        op.add_column("file_meta", sa.Column("session_id", sa.String(length=36), nullable=True))
    if "session_id" not in _columns("artifacts"):
        op.add_column("artifacts", sa.Column("session_id", sa.String(length=36), nullable=True))

    if "ix_sessions_tenant_user_updated" not in _indexes("sessions"):
        op.create_index(
            "ix_sessions_tenant_user_updated", "sessions", ["tenant_key", "user_id", "updated_at"]
        )
    if "ix_file_meta_session_id" not in _indexes("file_meta"):
        op.create_index("ix_file_meta_session_id", "file_meta", ["session_id"])
    if "ix_artifacts_session_id" not in _indexes("artifacts"):
        op.create_index("ix_artifacts_session_id", "artifacts", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_artifacts_session_id", table_name="artifacts")
    op.drop_index("ix_file_meta_session_id", table_name="file_meta")
    op.drop_index("ix_sessions_tenant_user_updated", table_name="sessions")
    op.drop_column("artifacts", "session_id")
    op.drop_column("file_meta", "session_id")
    op.drop_column("sessions", "updated_at")
    op.drop_column("sessions", "title")
