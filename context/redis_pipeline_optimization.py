from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from redis.asyncio import Redis


@asynccontextmanager
async def redis_pipeline_ctx(
    redis: Redis,
) -> AsyncGenerator:
    """Pipeline context to batch Redis commands and reduce packet count.

    Reduces 705 packets → ~50-100 by batching small commands.
    """
    async with redis.pipeline(transaction=False) as pipe:
        yield pipe
        await pipe.execute()


# Usage - batch FTA score reads instead of individual GETs
async def get_fta_scores_batch(
    redis: Redis,
    pairs: list[str],
) -> dict[str, float | None]:
    """Batch-fetch FTA scores for multiple pairs.

    Args:
        redis: Async Redis client.
        pairs: List of forex pairs (e.g., ["EURUSD", "GBPJPY"]).

    Returns:
        Dict mapping pair to FTA score (None if missing).
    """
    async with redis_pipeline_ctx(redis) as pipe:
        for pair in pairs:
            pipe.get(f"fta:score:{pair}")
        results = await pipe.execute()

    return {pair: float(score) if score else None for pair, score in zip(pairs, results, strict=False)}
