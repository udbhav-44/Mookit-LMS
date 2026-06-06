import logging

from sqlalchemy import insert

from ..contracts.context import RequestContext
from ..store.db import AuditLog


class AuditLogger:
    def __init__(self, session_factory):
        self.session_factory = session_factory
        self.logger = logging.getLogger("audit")

    async def log(self, ctx: RequestContext, action: str, tool: str | None = None,
                  status: str = "success", model: str | None = None,
                  tokens: int | None = None, cost: float | None = None):
        # 1. Log to Python logger (standard output/file)
        self.logger.info(
            f"AUDIT: tenant={ctx.tenant_key} user={ctx.user_id} "
            f"action={action} tool={tool} status={status}"
        )
        
        # 2. Log to DB
        async with self.session_factory() as session:
            stmt = insert(AuditLog).values(
                tenant_key=ctx.tenant_key,
                instance_id=ctx.instance_id,
                user_id=ctx.user_id,
                session_id=ctx.session_id,
                request_id=ctx.request_id,
                action=action,
                tool=tool,
                status=status,
                model=model,
                tokens=tokens,
                cost=cost
            )
            await session.execute(stmt)
            await session.commit()
