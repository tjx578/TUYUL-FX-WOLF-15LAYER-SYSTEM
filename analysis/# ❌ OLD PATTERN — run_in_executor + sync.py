# ❌ OLD PATTERN — run_in_executor + sync Redis + sleep(1)  # noqa: N999
import asyncio

import redis

r = redis.Redis()


async def consume():
    loop = asyncio.get_event_loop()
    while True:
        try:
            await loop.run_in_executor(None, r.xreadgroup, ...)  # pyright: ignore[reportArgumentType]
            # process but never XACK
        except Exception:
            await asyncio.sleep(1)  # linear, no backoff


# ✅ NEW PATTERN — native async + XACK + exponential backoff
from infrastructure.backoff import BackoffConfig  # noqa: E402
from infrastructure.stream_consumer import ConsumerConfig, StreamBinding, StreamConsumer  # noqa: E402


async def handle_candle(stream: str, msg_id: str, fields: dict[str, str]) -> None:
    fields["symbol"]
    # ... process candle ...
    # XACK happens automatically after this returns successfully


consumer = StreamConsumer(
    bindings=[
        StreamBinding(
            stream="candles:m1",
            group="analysis_group",
            callback=handle_candle,
        ),
    ],
    config=ConsumerConfig(
        backoff=BackoffConfig(initial=1.0, maximum=30.0, factor=2.0),
    ),
)


async def main():
    await consumer.start()


if __name__ == "__main__":
    asyncio.run(main())
