from __future__ import annotations

from collections.abc import Mapping

from state.ingest_state_consumer import IngestStateConsumer


class _FakeRedis:
    def __init__(self, payloads: Mapping[str, str | None]) -> None:
        self.payloads = payloads
        self.calls = 0

    def get(self, key: str) -> str | None:
        self.calls += 1
        return self.payloads.get(key)


class _WrapperRedis:
    def __init__(self, payloads: Mapping[str, str | None]) -> None:
        self.client = _FakeRedis(payloads)

    def get(self, key: str) -> str | None:
        raise AssertionError("wrapper get() should not be used by IngestStateConsumer")


def test_ingest_state_consumer_blocks_no_producer() -> None:
    consumer = IngestStateConsumer(redis_client=_FakeRedis({}), now_fn=lambda: 100.0)

    decision = consumer.is_blocking()

    assert decision.blocking is True
    assert decision.state == "NO_PRODUCER"
    assert decision.reason == "ingest_no_producer"


def test_ingest_state_consumer_blocks_long_degraded_provider_age() -> None:
    redis_payloads = {
        "wolf15:heartbeat:ingest:process": '{"producer":"ingest_service","ts":98.0}',
        "wolf15:heartbeat:ingest:provider": '{"producer":"finnhub_ws","ts":10.0}',
    }
    consumer = IngestStateConsumer(redis_client=_FakeRedis(redis_payloads), now_fn=lambda: 100.0)

    decision = consumer.is_blocking()

    assert decision.blocking is True
    assert decision.state == "DEGRADED"
    assert decision.reason.startswith("ingest_degraded_too_long:age=")


def test_ingest_state_consumer_allows_healthy_state_and_uses_cache() -> None:
    fake_redis = _FakeRedis(
        {
            "wolf15:heartbeat:ingest:process": '{"producer":"ingest_service","ts":98.0}',
            "wolf15:heartbeat:ingest:provider": '{"producer":"finnhub_ws","ts":99.0}',
        }
    )
    consumer = IngestStateConsumer(redis_client=fake_redis, now_fn=lambda: 100.0)

    first = consumer.is_blocking()
    second = consumer.is_blocking()

    assert first.blocking is False
    assert first.state == "HEALTHY"
    assert second.blocking is False
    assert fake_redis.calls == 2


def test_ingest_state_consumer_allows_short_degraded_grace() -> None:
    redis_payloads = {
        "wolf15:heartbeat:ingest:process": '{"producer":"ingest_service","ts":98.0}',
        "wolf15:heartbeat:ingest:provider": '{"producer":"finnhub_ws","ts":50.0}',
    }
    consumer = IngestStateConsumer(redis_client=_FakeRedis(redis_payloads), now_fn=lambda: 100.0)

    decision = consumer.is_blocking()

    assert decision.blocking is False
    assert decision.state == "DEGRADED"
    assert decision.reason == "ingest_degraded_within_grace"


def test_ingest_state_consumer_uses_direct_client_when_wrapper_exposes_client() -> None:
    consumer = IngestStateConsumer(
        redis_client=_WrapperRedis(
            {
                "wolf15:heartbeat:ingest:process": '{"producer":"ingest_service","ts":98.0}',
                "wolf15:heartbeat:ingest:provider": '{"producer":"finnhub_ws","ts":99.0}',
            }
        ),
        now_fn=lambda: 100.0,
    )

    decision = consumer.is_blocking()

    assert decision.blocking is False
    assert decision.state == "HEALTHY"
