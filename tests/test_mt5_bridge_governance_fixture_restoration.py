from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.integration.test_mt5_bridge_postgres_e2e import (
    _assert_governance_restored_exactly,
    _governance_fingerprint,
    _governance_snapshot,
)


def _baseline() -> dict[str, object]:
    return {
        "singleton_id": 1,
        "kill_switch_active": True,
        "kill_switch_reason": "MIGRATION_DEFAULT",
        "governance_version": 1,
        "updated_by": "MIGRATION",
        "updated_at": datetime(2026, 8, 1, tzinfo=UTC),
    }


class _AsyncpgRecordDouble:
    """Match asyncpg.Record: iteration yields values while keys expose columns."""

    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def __iter__(self):
        return iter(self._values.values())

    def keys(self):
        return self._values.keys()

    def __getitem__(self, key: str) -> object:
        return self._values[key]


def test_governance_snapshot_uses_record_mapping_not_value_iteration() -> None:
    baseline = _baseline()

    assert _governance_snapshot(_AsyncpgRecordDouble(baseline)) == baseline


def test_exact_governance_restoration_preserves_values_and_fingerprint() -> None:
    baseline = _baseline()
    restored = dict(baseline)

    _assert_governance_restored_exactly(baseline, restored)

    assert _governance_fingerprint(restored) == _governance_fingerprint(baseline)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("governance_version", 2),
        ("kill_switch_reason", "same state, different reason"),
        ("updated_by", "integration:fixture"),
        ("updated_at", datetime(2026, 8, 1, tzinfo=UTC) + timedelta(microseconds=1)),
    ],
)
def test_governance_restoration_rejects_metadata_drift(
    field: str,
    replacement: object,
) -> None:
    baseline = _baseline()
    restored = {**baseline, field: replacement}

    with pytest.raises(RuntimeError, match="exact restoration failed"):
        _assert_governance_restored_exactly(baseline, restored)


def test_governance_restoration_rejects_same_state_with_extra_metadata() -> None:
    baseline = _baseline()
    restored = {**baseline, "configuration_metadata": {"source": "cleanup"}}

    with pytest.raises(RuntimeError, match="exact restoration failed"):
        _assert_governance_restored_exactly(baseline, restored)
