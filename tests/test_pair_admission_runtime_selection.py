from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

GRANTED_AT = datetime(2026, 8, 3, 11, 5, tzinfo=UTC)


def _grant() -> dict[str, object]:
    return {
        "pair_admission_id": "5scr-admission:" + "a" * 32,
        "symbol": "EURUSD",
        "status": "GRANTED",
        "granted_at_utc": GRANTED_AT.isoformat(),
        "expires_at_utc": (GRANTED_AT + timedelta(minutes=15)).isoformat(),
    }


def _report(as_of: datetime | None) -> dict[str, object]:
    report: dict[str, object] = {"pair_admission_grants": [_grant()]}
    if as_of is not None:
        report["data_quality"] = {"end_utc": as_of.isoformat()}
    return report


def test_runtime_selects_only_an_active_pair_admission() -> None:
    selected = WolfConstitutionalPipeline._pair_admission_candidate(
        symbol="EURUSD",
        report=_report(GRANTED_AT + timedelta(minutes=5)),
    )

    assert selected["pair_admission_id"] == "5scr-admission:" + "a" * 32


def test_runtime_rejects_expired_pair_admission() -> None:
    selected = WolfConstitutionalPipeline._pair_admission_candidate(
        symbol="EURUSD",
        report=_report(GRANTED_AT + timedelta(minutes=15)),
    )

    assert selected == {}


def test_runtime_fails_closed_without_an_as_of_timestamp() -> None:
    selected = WolfConstitutionalPipeline._pair_admission_candidate(
        symbol="EURUSD",
        report=_report(None),
    )

    assert selected == {}
