import logging
import time

from fastapi import HTTPException

logger = logging.getLogger(__name__)


async def check_rate_limit(redis, tenant_key: str, rpm: int) -> None:
    """Sliding-window per-tenant rate limiter backed by Redis.

    Uses two adjacent 1-minute buckets to smooth window transitions.
    Raises HTTP 429 if the computed rate exceeds `rpm`.
    """
    now = time.time()
    current_minute = int(now) // 60
    prev_minute = current_minute - 1
    elapsed_in_window = now - current_minute * 60  # 0.0 – 59.999

    curr_key = f"{tenant_key}:rl:{current_minute}"
    prev_key = f"{tenant_key}:rl:{prev_minute}"

    pipe = redis.pipeline()
    pipe.incr(curr_key)
    pipe.expire(curr_key, 120)
    pipe.get(prev_key)
    results = await pipe.execute()

    curr_count = int(results[0])
    prev_count = int(results[2] or 0)

    # Weight the previous window by the fraction of the current window not yet elapsed.
    # This avoids the hard reset spike at the minute boundary.
    weighted = prev_count * (1 - elapsed_in_window / 60) + curr_count

    if weighted > rpm:
        logger.warning("Rate limit exceeded for tenant %s: %.1f req/min > %d", tenant_key, weighted, rpm)
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please slow down.",
            headers={"Retry-After": "60"},
        )
