# ❌ OLD — sync Redis in executor (blocking, wasteful)
# loop.run_in_executor(None, redis_client.xreadgroup, ...)

# ✅ NEW — native async
from infrastructure.stream_consumer import StreamConsumer, StreamBinding

async def handle_signal(stream: str, msg_id: str, fields: dict[str, str]) -> None:
    """Process a signal message. Called by StreamConsumer after XREADGROUP."""
    symbol = fields.get("symbol", "")
    verdict = fields.get("verdict", "")
    # ... your processing logic ...

consumer = StreamConsumer(
    bindings=[
        StreamBinding(
            stream="signals:l12",
            group="engine_group",
            callback=handle_signal,
        ),
    ],
)

# In your async main:
async def main():
    await consumer.start()  # Blocks until stop() called

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
