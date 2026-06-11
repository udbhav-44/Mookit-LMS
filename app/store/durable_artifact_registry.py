import builtins
import uuid

from sqlalchemy import insert, select, update

from ..contracts.context import RequestContext
from ..contracts.stores import Artifact
from ..contracts.stores import ArtifactRegistry as IArtifactRegistry
from ..store.db import Artifact as ArtifactModel


class DurableArtifactRegistry(IArtifactRegistry):
    """Redis hot-cache + Postgres durable storage for artifacts.

    Focus stack: Redis list at focus:{tenant_key}:{user_id}:{session_id}
                 (recent artifact_ids, newest first, max depth 10)
    Artifacts:   Postgres `artifacts` table (tenant-scoped via tenant_key).
    """

    def __init__(self, session_factory, redis):
        self.session_factory = session_factory
        self.redis = redis

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def add(self, ctx: RequestContext, art: Artifact) -> str:
        art_id = art.id or str(uuid.uuid4())
        async with self.session_factory() as session:
            stmt = insert(ArtifactModel).values(
                id=art_id,
                tenant_key=ctx.tenant_key,
                type=art.type,
                title=art.title,
                status=art.status,
                version=art.version,
                payload=art.payload,
                provenance=art.provenance,
                user_id=ctx.user_id,
            )
            await session.execute(stmt)
            await session.commit()
        await self.push_focus(ctx, art_id)
        return art_id

    async def get(self, ctx: RequestContext, artifact_id: str) -> Artifact | None:
        async with self.session_factory() as session:
            stmt = select(ArtifactModel).where(
                ArtifactModel.id == artifact_id,
                ArtifactModel.tenant_key == ctx.tenant_key,  # tenant isolation enforced here
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

        if row is None:
            return None

        return Artifact(
            id=row.id,
            type=row.type,
            title=row.title,
            status=row.status,
            version=row.version,
            payload=row.payload,
            provenance=row.provenance,
            namespaced_id=f"{ctx.tenant_key}:{ctx.user_id}:{row.id}",
        )

    async def update(self, ctx: RequestContext, artifact_id: str, patch: dict) -> Artifact:
        async with self.session_factory() as session:
            stmt = (
                update(ArtifactModel)
                .where(
                    ArtifactModel.id == artifact_id,
                    ArtifactModel.tenant_key == ctx.tenant_key,
                )
                .values(**patch, version=ArtifactModel.version + 1)
            )
            await session.execute(stmt)
            await session.commit()

        updated = await self.get(ctx, artifact_id)
        if updated is None:
            raise ValueError(f"Artifact {artifact_id} not found after update")
        return updated

    async def list(self, ctx: RequestContext, *, type: str | None = None) -> list[Artifact]:
        async with self.session_factory() as session:
            stmt = select(ArtifactModel).where(
                ArtifactModel.tenant_key == ctx.tenant_key,
                ArtifactModel.user_id == ctx.user_id,
            )
            if type:
                stmt = stmt.where(ArtifactModel.type == type)
            result = await session.execute(stmt)
            rows = result.scalars().all()

        return [
            Artifact(
                id=row.id,
                type=row.type,
                title=row.title,
                status=row.status,
                version=row.version,
                payload=row.payload,
                provenance=row.provenance,
                namespaced_id=f"{ctx.tenant_key}:{ctx.user_id}:{row.id}",
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Focus stack — artifact_ids only (contract: list[str])
    # ------------------------------------------------------------------

    def _focus_key(self, ctx: RequestContext) -> str:
        return f"focus:{ctx.tenant_key}:{ctx.user_id}:{ctx.session_id}"

    async def focus(self, ctx: RequestContext) -> builtins.list[str]:
        """Return the top-of-focus-stack artifact IDs (most recently pushed first)."""
        key = self._focus_key(ctx)
        raw = await self.redis.lrange(key, 0, 4)  # top 5
        return [aid if isinstance(aid, str) else aid.decode() for aid in raw]

    async def push_focus(self, ctx: RequestContext, artifact_id: str) -> None:
        key = self._focus_key(ctx)
        pipe = self.redis.pipeline()
        pipe.lrem(key, 0, artifact_id)   # remove duplicates first
        pipe.lpush(key, artifact_id)      # push to front
        pipe.ltrim(key, 0, 9)            # keep max 10 entries
        pipe.expire(key, 86400)
        await pipe.execute()
