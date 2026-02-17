from analysis.candle_builder import process_tick_for_candle, update_vwap
from infrastructure.stream_consumer import ConsumerConfig, StreamBinding, StreamConsumer


# Producer (tick ingestion)
async def publish_tick(symbol: str, tick_data: dict):
    await redis_client.xadd(  # noqa: F821 # pyright: ignore[reportUndefinedVariable]
        f"ticks:{symbol}",
        fields=tick_data,
        maxlen=10000  # auto-trim old ticks
    )

# Consumer 1: CandleBuilder
candle_consumer = StreamConsumer(
    bindings=[
        StreamBinding(
            stream="ticks:EURUSD",
            group="candle_builder_group",
            callback=process_tick_for_candle, # pyright: ignore[reportArgumentType]
        )
    ],
    config=ConsumerConfig(...) # pyright: ignore[reportArgumentType]
)

# Consumer 2: VWAP
vwap_consumer = StreamConsumer(
    bindings=[
        StreamBinding(
            stream="ticks:EURUSD",
            group="vwap_group",  # Different group = independent consumption
            callback=update_vwap, # pyright: ignore[reportArgumentType]
        )
    ],
    config=ConsumerConfig(...) # pyright: ignore[reportArgumentType]
)
