from __future__ import annotations

from dataclasses import replace

import pytest

from tests.redis_fixture_isolation import (
    RedisKeySnapshot,
    assert_only_declared_keys_changed,
    assert_redis_key_matches,
)


class _SnapshotClient:
    def __init__(self, snapshot: RedisKeySnapshot) -> None:
        self.snapshot = snapshot

    def type(self, key: str) -> str:
        assert key == self.snapshot.key
        return self.snapshot.key_type if self.snapshot.exists else "none"

    def dump(self, key: str) -> bytes | None:
        assert key == self.snapshot.key
        return self.snapshot.dump_payload

    def pttl(self, key: str) -> int:
        assert key == self.snapshot.key
        return self.snapshot.pttl_milliseconds

    def llen(self, key: str) -> int:
        assert key == self.snapshot.key
        return self.snapshot.cardinality


def _baseline() -> RedisKeySnapshot:
    return RedisKeySnapshot(
        key="owned:key",
        exists=True,
        key_type="list",
        pttl_milliseconds=5_000,
        dump_payload=b"canonical-value",
        cardinality=2,
        captured_at_milliseconds=1_000,
    )


def test_fixture_residue_is_detected_when_owned_key_should_be_absent() -> None:
    absent = RedisKeySnapshot("owned:key", False, "none", -2, None, 0, 1_000)
    residue = replace(absent, exists=True, key_type="list", pttl_milliseconds=-1, dump_payload=b"x", cardinality=1)
    with pytest.raises(AssertionError, match="existence drift"):
        assert_redis_key_matches(_SnapshotClient(residue), absent, now_milliseconds=1_000)


def test_fixture_deleting_unowned_key_is_rejected() -> None:
    with pytest.raises(AssertionError, match="unowned keys"):
        assert_only_declared_keys_changed(
            {"owned:key": "a", "foreign:key": "b"},
            {"owned:key": "c"},
            {"owned:key"},
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"dump_payload": b"different"}, "value drift"),
        ({"pttl_milliseconds": 4_000}, "TTL drift"),
        ({"cardinality": 3}, "cardinality drift"),
    ],
)
def test_exact_restoration_rejects_value_ttl_or_cardinality_drift(mutation: dict[str, object], message: str) -> None:
    baseline = _baseline()
    actual = replace(baseline, **mutation)
    with pytest.raises(AssertionError, match=message):
        assert_redis_key_matches(
            _SnapshotClient(actual),
            baseline,
            now_milliseconds=1_000,
            ttl_tolerance_milliseconds=0,
        )
