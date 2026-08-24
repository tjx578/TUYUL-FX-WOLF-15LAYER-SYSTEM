"""Generate the committed WLA-02 golden corpus from pinned typed inputs."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from contracts.alpha_learning_envelope_v1 import (
    AlphaLearningEnvelopeV1,
    EvidenceRefV1,
    QualityV1,
    SourceIdentityV1,
    SourceTimingV1,
    StreamPositionV1,
    alpha_learning_sha256,
    canonical_alpha_learning_json_bytes,
)
from contracts.wla02_golden_corpus import (
    CounterfactualMarketOutcomeSourceV1,
    DecisionSourceV1,
    GoldenCorpusEntryV1,
    RealizedBrokerOutcomeSourceV1,
    UnavailableOutcomeSourceV1,
    build_golden_envelope_v1,
    canonical_golden_corpus_json_bytes,
    replay_golden_corpus_v1,
)
from tests.wla01_contract.fixture_factory import (
    ALPHA_TEST_PRODUCER_KEY_ID,
    OUTCOME_TEST_PRODUCER_KEY_ID,
    PLACEHOLDER_SIGNATURE,
    producer_key_registry,
    sign_fixture_envelope,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "wla02"
IMPLEMENTATION_BASE_SHA = "97567f6070cfa6584dcbe32fb442498ee45382c2"
TARGET_BASE_SHA = "22ee9774930d2bf5d09a32851098a8dba8918167"
NOW = datetime(2026, 8, 24, 16, 0, 0, tzinfo=UTC)
CORRELATION_ID = UUID("bbb42de5-d85f-59cf-a1fe-9c60345d6e64")
PRODUCER_RUN_ID = UUID("da48674a-c9b7-51fc-8fc8-3642a116f2b5")


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return canonical_golden_corpus_json_bytes(value)


def evidence_ref(ref_type: str, ref_id: str) -> EvidenceRefV1:
    return EvidenceRefV1.model_validate(
        {
            "ref_type": ref_type,
            "ref_id": ref_id,
            "ref_hash": _sha256_bytes(ref_id.encode("utf-8")),
        }
    )


def source_identity() -> SourceIdentityV1:
    return SourceIdentityV1(
        source_system="WOLF15",
        source_service="canonical-alpha-export",
        code_revision=TARGET_BASE_SHA,
        deployment_id="offline-wla02-golden-corpus",
        policy_version="wolf15.wla02.mapper.v1",
        config_version="wolf15.wla02.fixture-config.v1",
    )


def timing(at: datetime) -> SourceTimingV1:
    return SourceTimingV1(
        occurred_at_utc=at,
        observed_at_utc=at + timedelta(milliseconds=100),
        source_published_at_utc=at + timedelta(milliseconds=200),
        source_precision="MILLISECOND",
        clock_status="SYNCHRONIZED",
        maximum_clock_skew_ms=250,
    )


def quality(*, correction_of_event_id: UUID | None = None) -> QualityV1:
    return QualityV1(
        evidence_status="VALID",
        reason_codes=(),
        missing_fields=(),
        uncertainty_flags=(),
        correction_of_event_id=correction_of_event_id,
        supersedes_event_id=None,
        invalidates_event_id=None,
    )


def decision_source(
    disposition: str,
    *,
    at: datetime,
    source_valid_for_execution: bool = False,
) -> DecisionSourceV1:
    slug = disposition.lower().replace("_", "-")
    return DecisionSourceV1.model_validate(
        {
            "record_type": "DECISION",
            "source_record_id": f"wolf15-decision:{slug}:001",
            "alpha_or_evaluation_id": f"alpha-evaluation:eurusd:{slug}:001",
            "symbol": "EURUSD",
            "disposition": disposition,
            "reason_codes": (f"SOURCE_{disposition}_OBSERVED",),
            "evidence_refs": (evidence_ref("WOLF15_SOURCE_RECORD", f"decision-source:{slug}:001"),),
            "decision_policy_version": "wolf15.alpha-policy.v1",
            "decided_at_utc": at,
            "source_valid_for_execution": source_valid_for_execution,
        }
    )


def realized_source(outcome_kind: str, *, at: datetime) -> RealizedBrokerOutcomeSourceV1:
    common: dict[str, Any] = {
        "record_type": "REALIZED_BROKER_OUTCOME",
        "evidence_class": "REALIZED_BROKER",
        "source_record_id": f"broker-outcome:{outcome_kind.lower()}:001",
        "decision_id": "alpha-evaluation:eurusd:buy:001",
        "outcome_kind": outcome_kind,
        "symbol": "EURUSD",
        "side": "BUY",
        "occurred_at_utc": at,
    }
    if outcome_kind == "EXECUTED":
        common.update(
            execution_id="execution-001",
            order_id="order-001",
            fill_id="fill-001",
            requested_quantity=Decimal("1.00000000"),
            filled_quantity=Decimal("1.00000000"),
            fill_price=Decimal("1.10250000"),
        )
    elif outcome_kind == "REJECTED":
        common.update(request_id="request-002", reason_code="SOURCE_RISK_REJECTED")
    else:
        common.update(order_id="order-003", reason_code="SOURCE_ORDER_EXPIRED", filled_quantity=Decimal("0"))
    return RealizedBrokerOutcomeSourceV1.model_validate(common)


def counterfactual_source(case_label: str, *, at: datetime, corrected: bool = False) -> CounterfactualMarketOutcomeSourceV1:
    suffix = "correction-1" if corrected else "original"
    return CounterfactualMarketOutcomeSourceV1(
        record_type="COUNTERFACTUAL_MARKET_OUTCOME",
        evidence_class="COUNTERFACTUAL_MARKET",
        source_record_id=f"market-horizon:{case_label.lower()}:{suffix}",
        alpha_id=f"alpha-evaluation:eurusd:{case_label.lower()}:001",
        outcome_kind="MARKET_HORIZON",
        symbol="EURUSD",
        occurred_at_utc=at,
        horizon_policy_version="wolf15.counterfactual-horizon.v1",
        horizon_seconds=3600,
        reference_price=Decimal("1.10250000"),
        observed_price=Decimal("1.10410000" if corrected else "1.10400000"),
    )


def unavailable_sources() -> dict[str, UnavailableOutcomeSourceV1]:
    return {
        "censored": UnavailableOutcomeSourceV1(
            record_type="UNAVAILABLE_OUTCOME",
            evidence_class="UNAVAILABLE",
            source_record_id="unavailable:censored:001",
            decision_id="alpha-evaluation:eurusd:wait:001",
            unavailable_kind="CENSORED",
            symbol="EURUSD",
            assessed_at_utc=NOW + timedelta(hours=4),
            reason_codes=("OBSERVATION_WINDOW_INCOMPLETE",),
            missing_fields=("observed_price",),
        ),
        "missing": UnavailableOutcomeSourceV1(
            record_type="UNAVAILABLE_OUTCOME",
            evidence_class="UNAVAILABLE",
            source_record_id="unavailable:missing:001",
            decision_id="alpha-evaluation:eurusd:no-trade:001",
            unavailable_kind="MISSING",
            symbol="EURUSD",
            assessed_at_utc=NOW + timedelta(hours=4, minutes=1),
            reason_codes=("SOURCE_EVIDENCE_ABSENT",),
            missing_fields=("market_observation", "observed_price"),
        ),
    }


def _event_ref_for_source(source: DecisionSourceV1 | RealizedBrokerOutcomeSourceV1 | CounterfactualMarketOutcomeSourceV1) -> EvidenceRefV1:
    if isinstance(source, DecisionSourceV1):
        return evidence_ref("WOLF15_SOURCE_RECORD", source.source_record_id)
    if isinstance(source, RealizedBrokerOutcomeSourceV1):
        return evidence_ref("WOLF15_EXECUTION", source.source_record_id)
    return evidence_ref("WOLF15_MARKET_OBSERVATION", source.source_record_id)


def _build_signed_envelope(
    source: DecisionSourceV1 | RealizedBrokerOutcomeSourceV1 | CounterfactualMarketOutcomeSourceV1,
    *,
    logical_event_key: str,
    stream: StreamPositionV1,
    correction_of_event_id: UUID | None = None,
) -> AlphaLearningEnvelopeV1:
    is_decision = isinstance(source, DecisionSourceV1)
    producer_key_id = ALPHA_TEST_PRODUCER_KEY_ID if is_decision else OUTCOME_TEST_PRODUCER_KEY_ID
    occurred_at = source.decided_at_utc if is_decision else source.occurred_at_utc
    unsigned = build_golden_envelope_v1(
        source_snapshot=source,
        logical_event_key=logical_event_key,
        correlation_id=CORRELATION_ID,
        causation_id=None,
        direct_source_refs=(_event_ref_for_source(source),),
        ancestry_manifest=None,
        stream=stream,
        source_identity=source_identity(),
        timing=timing(occurred_at),
        quality=quality(correction_of_event_id=correction_of_event_id),
        producer_run_id=PRODUCER_RUN_ID,
        producer_key_id=producer_key_id,
        producer_signature=PLACEHOLDER_SIGNATURE,
    )
    return sign_fixture_envelope(unsigned)


def _entry(
    source: DecisionSourceV1 | RealizedBrokerOutcomeSourceV1 | CounterfactualMarketOutcomeSourceV1,
    *,
    fixture_id: str,
    case_label: str,
    evidence_class: str,
    known_at_utc: datetime,
    logical_event_key: str | None = None,
    stream: StreamPositionV1 | None = None,
    correction_of_event_id: UUID | None = None,
) -> GoldenCorpusEntryV1:
    occurred_at = source.decided_at_utc if isinstance(source, DecisionSourceV1) else source.occurred_at_utc
    logical_key = logical_event_key if logical_event_key is not None else f"wla02|{fixture_id}"
    actual_stream = stream or StreamPositionV1(
        stream_id=f"wla02:{fixture_id}",
        stream_sequence=1,
        previous_stream_sequence=None,
        previous_event_hash=None,
        ordering_scope="SOURCE_STREAM",
    )
    envelope = _build_signed_envelope(
        source,
        logical_event_key=logical_key,
        stream=actual_stream,
        correction_of_event_id=correction_of_event_id,
    )
    return GoldenCorpusEntryV1.model_validate(
        {
            "entry_version": "wolf15.wla02.golden-corpus-entry.v1",
            "fixture_id": fixture_id,
            "case_label": case_label,
            "evidence_class": evidence_class,
            "valid_at_utc": occurred_at,
            "known_at_utc": known_at_utc,
            "correction_of_event_id": correction_of_event_id,
            "source_snapshot_hash": alpha_learning_sha256(source.model_dump(mode="json")),
            "source_snapshot": source,
            "envelope_canonical_json": canonical_alpha_learning_json_bytes(envelope).decode("utf-8"),
        }
    )


def positive_entries() -> dict[str, GoldenCorpusEntryV1]:
    result: dict[str, GoldenCorpusEntryV1] = {}
    decision_specs = (
        ("EXECUTED", "BUY", True),
        ("WAIT", "WAIT", False),
        ("HOLD", "HOLD", False),
        ("NO_TRADE", "NO_TRADE", False),
        ("CONFLICT", "CONFLICT", False),
    )
    for index, (case_label, disposition, execution_valid) in enumerate(decision_specs):
        at = NOW + timedelta(minutes=index)
        fixture_id = f"decision.{case_label.lower().replace('_', '-')}"
        result[fixture_id] = _entry(
            decision_source(disposition, at=at, source_valid_for_execution=execution_valid),
            fixture_id=fixture_id,
            case_label=case_label,
            evidence_class="WOLF15_DECISION",
            known_at_utc=at + timedelta(seconds=1),
        )

    for index, outcome_kind in enumerate(("EXECUTED", "REJECTED", "EXPIRED"), start=10):
        at = NOW + timedelta(minutes=index)
        fixture_id = f"realized.{outcome_kind.lower()}"
        result[fixture_id] = _entry(
            realized_source(outcome_kind, at=at),
            fixture_id=fixture_id,
            case_label=outcome_kind,
            evidence_class="REALIZED_BROKER",
            known_at_utc=at + timedelta(seconds=2),
        )

    counterfactual_original: GoldenCorpusEntryV1 | None = None
    for index, case_label in enumerate(("WAIT", "HOLD", "NO_TRADE", "CONFLICT"), start=20):
        at = NOW + timedelta(hours=1, minutes=index)
        fixture_id = f"counterfactual.{case_label.lower().replace('_', '-')}"
        entry = _entry(
            counterfactual_source(case_label, at=at),
            fixture_id=fixture_id,
            case_label=case_label,
            evidence_class="COUNTERFACTUAL_MARKET",
            known_at_utc=at + timedelta(seconds=3),
        )
        result[fixture_id] = entry
        if case_label == "CONFLICT":
            counterfactual_original = entry

    assert counterfactual_original is not None
    original_envelope = counterfactual_original.envelope
    correction_at = original_envelope.timing.occurred_at_utc + timedelta(minutes=1)
    correction_source = counterfactual_source("CONFLICT", at=correction_at, corrected=True)
    correction_fixture_id = "counterfactual.conflict.correction-1"
    result[correction_fixture_id] = _entry(
        correction_source,
        fixture_id=correction_fixture_id,
        case_label="CONFLICT",
        evidence_class="COUNTERFACTUAL_MARKET",
        known_at_utc=counterfactual_original.known_at_utc + timedelta(minutes=2),
        logical_event_key="wla02|counterfactual.conflict|correction-1",
        stream=StreamPositionV1(
            stream_id=original_envelope.stream.stream_id,
            stream_sequence=2,
            previous_stream_sequence=1,
            previous_event_hash=original_envelope.integrity.envelope_hash,
            ordering_scope="SOURCE_STREAM",
        ),
        correction_of_event_id=original_envelope.identity.event_id,
    )
    return result


def future_leakage_canary(entries: dict[str, GoldenCorpusEntryV1]) -> GoldenCorpusEntryV1:
    base = entries["counterfactual.wait"]
    raw = base.model_dump(mode="python")
    raw["fixture_id"] = "canary.future-leakage"
    raw["known_at_utc"] = max(item.known_at_utc for item in entries.values()) + timedelta(days=1)
    return GoldenCorpusEntryV1.model_validate(raw)


def generated_artifacts() -> dict[str, bytes]:
    entries = positive_entries()
    artifacts: dict[str, bytes] = {}
    for fixture_id, entry in sorted(entries.items()):
        artifacts[f"positive/{fixture_id}.json"] = _canonical_bytes(entry)

    canary = future_leakage_canary(entries)
    artifacts["canaries/future_leakage.entry.json"] = _canonical_bytes(canary)

    for name, source in sorted(unavailable_sources().items()):
        artifacts[f"negative/{name}.source.json"] = _canonical_bytes(source)

    replay = replay_golden_corpus_v1(
        tuple(entries.values()),
        valid_time_cutoff_utc=max(item.valid_at_utc for item in entries.values()),
        knowledge_time_cutoff_utc=max(item.known_at_utc for item in entries.values()),
        key_registry=producer_key_registry(),
    )
    manifest_entries = [
        {
            "path": path,
            "sha256": _sha256_bytes(content),
        }
        for path, content in sorted(artifacts.items())
    ]
    manifest = {
        "manifest_version": "wolf15.wla02.golden-corpus-manifest.v1",
        "implementation_base_sha": IMPLEMENTATION_BASE_SHA,
        "target_base_sha": TARGET_BASE_SHA,
        "generator": "python -m tests.wla02_golden.fixture_factory",
        "positive_entry_count": len(entries),
        "realized_and_counterfactual_are_distinct": True,
        "runtime_authority": "NONE",
        "history_hash": replay.history_hash,
        "effective_hash": replay.effective_hash,
        "artifacts": manifest_entries,
    }
    artifacts["manifest.json"] = _canonical_bytes(manifest)
    return artifacts


def write_fixtures() -> None:
    artifacts = generated_artifacts()
    for relative_path, content in artifacts.items():
        path = FIXTURE_ROOT / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def verify_committed_fixtures() -> None:
    expected = generated_artifacts()
    actual_paths = {
        path.relative_to(FIXTURE_ROOT).as_posix(): path.read_bytes()
        for path in FIXTURE_ROOT.rglob("*.json")
    }
    if actual_paths != expected:
        missing = sorted(set(expected) - set(actual_paths))
        extra = sorted(set(actual_paths) - set(expected))
        changed = sorted(path for path in set(expected) & set(actual_paths) if expected[path] != actual_paths[path])
        raise AssertionError(f"WLA-02 fixture drift: missing={missing}, extra={extra}, changed={changed}")


if __name__ == "__main__":
    write_fixtures()
    verify_committed_fixtures()
    manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    print(f"WLA-02 fixtures verified: {manifest['positive_entry_count']} positive entries")
