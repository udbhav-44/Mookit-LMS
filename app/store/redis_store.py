import json
from typing import List, Optional

import redis.asyncio as aioredis

from ..contracts.stores import SessionStore as ISessionStore, Message
from ..contracts.context import RequestContext


class RedisSessionStore(ISessionStore):
    """Redis-backed session store.

    Transcript: Redis list at  {tenant_key}:session:{session_id}:transcript
    Summary:    Redis string at {tenant_key}:session:{session_id}:summary

    Both keys have a 24-hour TTL that is refreshed on each write.
    """

    _TTL = 86400  # 24 hours

    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client

    def _transcript_key(self, ctx: RequestContext) -> str:
        return f"{ctx.tenant_key}:session:{ctx.session_id}:transcript"

    def _summary_key(self, ctx: RequestContext) -> str:
        return f"{ctx.tenant_key}:session:{ctx.session_id}:summary"

    async def append_message(
        self, ctx: RequestContext, role: str, content: str, meta: dict | None = None
    ) -> None:
        key = self._transcript_key(ctx)
        msg = Message(role=role, content=content, meta=meta)
        pipe = self.redis.pipeline()
        pipe.rpush(key, msg.model_dump_json())
        pipe.expire(key, self._TTL)
        await pipe.execute()

    async def get_transcript(self, ctx: RequestContext, *, max_tokens: int) -> List[Message]:
        key = self._transcript_key(ctx)
        raw_msgs = await self.redis.lrange(key, 0, -1)
        messages = [Message.model_validate_json(m) for m in raw_msgs]

        # Trim to max_tokens from the end (most-recent messages) using a rough char proxy.
        # Dev B's compaction logic sets `max_tokens`; we honour the limit here.
        total = 0
        trimmed: List[Message] = []
        for msg in reversed(messages):
            token_est = len(msg.content) // 4  # ~4 chars per token rough estimate
            if total + token_est > max_tokens and trimmed:
                break
            trimmed.append(msg)
            total += token_est
        return list(reversed(trimmed))

    async def set_summary(self, ctx: RequestContext, summary: str) -> None:
        key = self._summary_key(ctx)
        await self.redis.set(key, summary, ex=self._TTL)

    async def get_summary(self, ctx: RequestContext) -> Optional[str]:
        key = self._summary_key(ctx)
        value = await self.redis.get(key)
        return value if isinstance(value, str) else (value.decode() if value else None)
