"""Integrity acceptance with no live collector, database or broker."""

import copy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from ops.mt5_mcp import reconcile
from ops.mt5_mcp.report_integrity import evidence_digest, seal_report, verify_report_integrity


def sealed():
    return seal_report(
        {"window": {"from": "fixture-start", "to": "fixture-end"}, "B-B16": "NOT_EXECUTED", "EXECUTION_READY": False},
        database={"measured": False},
        broker={"snapshots": {}},
        sources_before={"fixture.py": "sha256:" + "1" * 64},
        sources_after={"fixture.py": "sha256:" + "1" * 64},
    )


def test_receipt_round_trip_requires_external_expected_digest():
    report = sealed()
    expected = report["integrity"]["receipt_digest"]
    assert verify_report_integrity(report, expected_receipt_digest=expected)
    assert not verify_report_integrity(report, expected_receipt_digest="")
    assert not verify_report_integrity(report, expected_receipt_digest="sha256:" + "0" * 64)


@pytest.mark.parametrize("field", ["window", "B-B16", "EXECUTION_READY"])
def test_report_payload_tamper_rejected(field):
    report = sealed()
    expected = report["integrity"]["receipt_digest"]
    report[field] = "tampered"
    assert not verify_report_integrity(report, expected_receipt_digest=expected)


@pytest.mark.parametrize(
    "field", ["database_snapshot_digest", "broker_snapshot_digest", "orchestrator_sources", "collector_identity"]
)
def test_receipt_tamper_rejected(field):
    report = sealed()
    expected = report["integrity"]["receipt_digest"]
    report["integrity"][field] = "tampered"
    assert not verify_report_integrity(report, expected_receipt_digest=expected)


def test_self_rehashed_tamper_cannot_match_retained_digest():
    report = sealed()
    expected = report["integrity"]["receipt_digest"]
    report["B-B16"] = "EXECUTED_PASS"
    report["integrity"]["report_payload_digest"] = evidence_digest(
        {k: v for k, v in report.items() if k != "integrity"}
    )
    report["integrity"]["receipt_digest"] = evidence_digest(
        {k: v for k, v in report["integrity"].items() if k != "receipt_digest"}
    )
    assert not verify_report_integrity(report, expected_receipt_digest=expected)


def test_missing_or_changed_sources_rejected():
    for before, after in [({}, {}), ({"source": "a"}, {"source": "b"})]:
        with pytest.raises(ValueError, match="SOURCE_CHANGED_OR_MISSING"):
            seal_report({}, database={}, broker={}, sources_before=before, sources_after=after)


def test_digest_supports_database_values_and_rejects_ambiguous_values():
    values = {"at": datetime(2026, 9, 9, tzinfo=UTC), "balance": Decimal("10.25")}
    assert evidence_digest(values) == evidence_digest(copy.deepcopy(values))
    for value in [float("nan"), Decimal("Infinity"), datetime(2026, 9, 9), object()]:
        with pytest.raises((TypeError, ValueError)):
            evidence_digest(value)


@pytest.mark.asyncio
async def test_real_run_orchestrator_seals_mocked_collection(monkeypatch, tmp_path):
    database = {"measured": False, "truncated": None}
    broker = {"tool_surface_exact": False, "snapshots": {}}
    monkeypatch.setattr(reconcile, "_database_snapshot", AsyncMock(return_value=database))
    monkeypatch.setattr(reconcile, "_broker_snapshot", AsyncMock(return_value=broker))
    report = await reconcile.run_reconciliation(dsn="fixture-only", repo_root=tmp_path, config_path=Path("unused"))
    receipt = report["integrity"]
    assert verify_report_integrity(report, expected_receipt_digest=receipt["receipt_digest"])
    assert receipt["database_snapshot_digest"] == evidence_digest(database)
    assert receipt["broker_snapshot_digest"] == evidence_digest(broker)
    assert receipt["collector_identity"] == "UNVERIFIED"
    assert report["EXECUTION_READY"] is False
    assert report["B-B16"] == "NOT_EXECUTED"
