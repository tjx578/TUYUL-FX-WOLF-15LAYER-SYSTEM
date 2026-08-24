"""Deterministically generate the committed WLA-01 contract fixtures."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from contracts.alpha_learning_envelope_v1 import (
    ALPHA_FACT_EVENT,
    ALPHA_LEARNING_SIGNATURE_DOMAIN,
    OUTCOME_EVIDENCE_EVENT,
    OUTCOME_EVIDENCE_SCHEMA_ID,
    AlphaLearningEnvelopeV1,
    AncestryManifestRefV1,
    CancelOutcomeEvidenceV1,
    CanonicalAlphaAbstentionFactV1,
    CanonicalAlphaDecisionFactV1,
    EvidenceRefV1,
    FillOutcomeEvidenceV1,
    HorizonObservationEvidenceV1,
    PartialFillOutcomeEvidenceV1,
    ProducerKeyBindingV1,
    QualityV1,
    RejectOutcomeEvidenceV1,
    SourceIdentityV1,
    SourceTimingV1,
    StreamPositionV1,
    alpha_learning_envelope_hash,
    alpha_learning_event_id,
    alpha_learning_sha256,
    alpha_learning_signature_preimage,
    build_alpha_learning_envelope_v1,
    canonical_alpha_learning_json_bytes,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "wla01"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "alpha_learning_envelope_v1.schema.json"
NOW = datetime(2026, 8, 24, 9, 0, 0, tzinfo=UTC)
CORRELATION_ID = UUID("0db3a9d3-3fc7-51d5-b04a-7c89ea0cb8c2")
PRODUCER_RUN_ID = UUID("9bb654e4-221e-5bbd-914f-b9c1402098d3")
ALPHA_TEST_PRODUCER_KEY_ID = "wolf15.canonical-alpha.fixture.ed25519.v1"
OUTCOME_TEST_PRODUCER_KEY_ID = "wolf15.outcome-evidence.fixture.ed25519.v1"
TEST_PRIVATE_KEY_SEEDS = {
    ALPHA_TEST_PRODUCER_KEY_ID: bytes.fromhex(
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
    ),
    OUTCOME_TEST_PRODUCER_KEY_ID: bytes.fromhex(
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb"
    ),
}
PLACEHOLDER_SIGNATURE = "base64url:" + "A" * 86


def _base64url(value: bytes) -> str:
    return "base64url:" + base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _test_private_key(key_id: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(TEST_PRIVATE_KEY_SEEDS[key_id])


def producer_key_binding(
    *,
    key_id: str = ALPHA_TEST_PRODUCER_KEY_ID,
    status: str = "ACTIVE",
    signature_domain: str = ALPHA_LEARNING_SIGNATURE_DOMAIN,
    producer_role: str | None = None,
    source_service: str = "canonical-alpha-export",
) -> ProducerKeyBindingV1:
    expected_role = (
        "WOLF15_CANONICAL_ALPHA"
        if key_id == ALPHA_TEST_PRODUCER_KEY_ID
        else "WOLF15_SOURCE_OUTCOME_EVIDENCE"
    )
    public_key = _test_private_key(key_id).public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return ProducerKeyBindingV1.model_validate(
        {
            "key_id": key_id,
            "algorithm": "ED25519",
            "signature_domain": signature_domain,
            "source_system": "WOLF15",
            "source_service": source_service,
            "producer_role": producer_role if producer_role is not None else expected_role,
            "status": status,
            "public_key": _base64url(public_key),
        }
    )


def producer_key_registry() -> dict[str, ProducerKeyBindingV1]:
    return {
        ALPHA_TEST_PRODUCER_KEY_ID: producer_key_binding(key_id=ALPHA_TEST_PRODUCER_KEY_ID),
        OUTCOME_TEST_PRODUCER_KEY_ID: producer_key_binding(key_id=OUTCOME_TEST_PRODUCER_KEY_ID),
    }


def sign_fixture_envelope(envelope: AlphaLearningEnvelopeV1) -> AlphaLearningEnvelopeV1:
    key_id = envelope.producer_authentication.key_id
    signature = _test_private_key(key_id).sign(alpha_learning_signature_preimage(envelope))
    raw = envelope.model_dump(mode="json")
    raw["producer_authentication"]["signature"] = _base64url(signature)
    return AlphaLearningEnvelopeV1.model_validate_json(canonical_alpha_learning_json_bytes(raw))


def source() -> SourceIdentityV1:
    return SourceIdentityV1(
        source_system="WOLF15",
        source_service="canonical-alpha-export",
        code_revision="7ff2a9194b22e185b35dc61574c61628ba404939",
        deployment_id="fixture-deployment-20260824",
        policy_version="wolf15.alpha-export.v1",
        config_version="wolf15.fixture-config.v1",
    )


def timing(at: datetime = NOW) -> SourceTimingV1:
    return SourceTimingV1(
        occurred_at_utc=at,
        observed_at_utc=at + timedelta(milliseconds=100),
        source_published_at_utc=at + timedelta(milliseconds=200),
        source_precision="MILLISECOND",
        clock_status="SYNCHRONIZED",
        maximum_clock_skew_ms=250,
    )


def valid_quality() -> QualityV1:
    return QualityV1(
        evidence_status="VALID",
        reason_codes=(),
        missing_fields=(),
        uncertainty_flags=(),
        correction_of_event_id=None,
        supersedes_event_id=None,
        invalidates_event_id=None,
    )


def direct_ref(ref_type: str, ref_id: str) -> EvidenceRefV1:
    return EvidenceRefV1.model_validate(
        {
            "ref_type": ref_type,
            "ref_id": ref_id,
            "ref_hash": "sha256:" + hashlib.sha256(ref_id.encode("utf-8")).hexdigest(),
        }
    )


def first_stream(stream_id: str) -> StreamPositionV1:
    return StreamPositionV1(
        stream_id=stream_id,
        stream_sequence=1,
        previous_stream_sequence=None,
        previous_event_hash=None,
        ordering_scope="SOURCE_STREAM",
    )


def build(
    *,
    event_name: str,
    logical_event_key: str,
    payload: Any,
    at: datetime = NOW,
    stream: StreamPositionV1 | None = None,
    refs: tuple[EvidenceRefV1, ...] | None = None,
    ancestry: AncestryManifestRefV1 | None = None,
) -> AlphaLearningEnvelopeV1:
    producer_key_id = (
        ALPHA_TEST_PRODUCER_KEY_ID if event_name == ALPHA_FACT_EVENT else OUTCOME_TEST_PRODUCER_KEY_ID
    )
    unsigned = build_alpha_learning_envelope_v1(
        event_name=event_name,  # type: ignore[arg-type]
        logical_event_key=logical_event_key,
        correlation_id=CORRELATION_ID,
        causation_id=None,
        direct_source_refs=refs
        if refs is not None
        else (direct_ref("WOLF15_SOURCE_RECORD", f"source:{logical_event_key}"),),
        ancestry_manifest=ancestry,
        stream=stream if stream is not None else first_stream(f"fixture:{logical_event_key}"),
        source=source(),
        timing=timing(at),
        quality=valid_quality(),
        producer_run_id=PRODUCER_RUN_ID,
        producer_key_id=producer_key_id,
        producer_signature=PLACEHOLDER_SIGNATURE,
        payload=payload,
    )
    return sign_fixture_envelope(unsigned)


def alpha_decision(at: datetime = NOW) -> CanonicalAlphaDecisionFactV1:
    return CanonicalAlphaDecisionFactV1(
        payload_type="canonical-alpha-decision.v1",
        alpha_id="alpha:eurusd:20260824T090000Z",
        symbol="EURUSD",
        decision="BUY",
        decision_reason_codes=("CANONICAL_POLICY_PASS", "RAW_EVIDENCE_COMPLETE"),
        evidence_refs=(
            direct_ref("WOLF15_ALPHA", "alpha-source:eurusd:20260824T090000Z"),
            direct_ref("WOLF15_SOURCE_RECORD", "pair-admission:eurusd:block-001"),
        ),
        decision_policy_version="wolf15.alpha-policy.v1",
        decided_at_utc=at,
        source_valid_for_execution=True,
    )


def alpha_abstention(at: datetime) -> CanonicalAlphaAbstentionFactV1:
    return CanonicalAlphaAbstentionFactV1(
        payload_type="canonical-alpha-abstention.v1",
        alpha_evaluation_id="alpha-evaluation:eurusd:20260824T090001Z",
        symbol="EURUSD",
        abstention_kind="INSUFFICIENT_EVIDENCE",
        reason_codes=("RAW_DURATION_BELOW_MINIMUM",),
        evidence_refs=(direct_ref("WOLF15_SOURCE_RECORD", "pair-admission:eurusd:block-002"),),
        decision_policy_version="wolf15.alpha-policy.v1",
        decided_at_utc=at,
        source_valid_for_execution=False,
    )


def positive_envelopes() -> dict[str, AlphaLearningEnvelopeV1]:
    alpha_first = build(
        event_name=ALPHA_FACT_EVENT,
        logical_event_key="alpha|eurusd|20260824T090000Z",
        payload=alpha_decision(),
        stream=first_stream("alpha:EURUSD"),
    )
    second_at = NOW + timedelta(seconds=1)
    alpha_second = build(
        event_name=ALPHA_FACT_EVENT,
        logical_event_key="alpha-abstention|eurusd|20260824T090001Z",
        payload=alpha_abstention(second_at),
        at=second_at,
        stream=StreamPositionV1(
            stream_id="alpha:EURUSD",
            stream_sequence=2,
            previous_stream_sequence=1,
            previous_event_hash=alpha_first.integrity.envelope_hash,
            ordering_scope="SOURCE_STREAM",
        ),
    )
    ancestry = AncestryManifestRefV1(
        manifest_id="manifest:alpha:eurusd:1-33",
        covered_sequence_start=1,
        covered_sequence_end=33,
        event_count=33,
        integrity_root="sha256:" + "a" * 64,
    )
    ancestry_event = build(
        event_name=ALPHA_FACT_EVENT,
        logical_event_key="alpha-abstention|eurusd|ancestry-33",
        payload=alpha_abstention(second_at),
        at=second_at,
        refs=(),
        ancestry=ancestry,
    )

    full_at = NOW + timedelta(minutes=1)
    full = build(
        event_name=OUTCOME_EVIDENCE_EVENT,
        logical_event_key="fill|execution-001|fill-001",
        payload=FillOutcomeEvidenceV1(
            payload_type="fill-evidence.v1",
            execution_id="execution-001",
            order_id="order-001",
            fill_id="fill-001",
            symbol="EURUSD",
            side="BUY",
            requested_quantity=Decimal("1.00000000"),
            filled_quantity=Decimal("1.00000000"),
            fill_price=Decimal("1.10250000"),
            filled_at_utc=full_at,
            finality="FULL",
        ),
        at=full_at,
    )
    partial_at = NOW + timedelta(minutes=2)
    partial = build(
        event_name=OUTCOME_EVIDENCE_EVENT,
        logical_event_key="partial-fill|execution-002|fill-002",
        payload=PartialFillOutcomeEvidenceV1(
            payload_type="partial-fill-evidence.v1",
            execution_id="execution-002",
            order_id="order-002",
            fill_id="fill-002",
            symbol="EURUSD",
            side="SELL",
            requested_quantity=Decimal("1.00000000"),
            cumulative_filled_quantity=Decimal("0.40000000"),
            remaining_quantity=Decimal("0.60000000"),
            fill_price=Decimal("1.10200000"),
            filled_at_utc=partial_at,
            finality="PARTIAL",
        ),
        at=partial_at,
    )
    reject_at = NOW + timedelta(minutes=3)
    reject = build(
        event_name=OUTCOME_EVIDENCE_EVENT,
        logical_event_key="reject|request-003",
        payload=RejectOutcomeEvidenceV1(
            payload_type="reject-evidence.v1",
            request_id="request-003",
            order_id=None,
            symbol="EURUSD",
            side="BUY",
            reason_code="SOURCE_RISK_REJECTED",
            rejected_at_utc=reject_at,
            finality="REJECTED",
        ),
        at=reject_at,
    )
    cancel_at = NOW + timedelta(minutes=4)
    cancel = build(
        event_name=OUTCOME_EVIDENCE_EVENT,
        logical_event_key="cancel|order-004",
        payload=CancelOutcomeEvidenceV1(
            payload_type="cancel-evidence.v1",
            order_id="order-004",
            symbol="EURUSD",
            side="SELL",
            reason_code="SOURCE_ORDER_EXPIRED",
            filled_quantity=Decimal("0.00000000"),
            cancelled_at_utc=cancel_at,
            finality="CANCELLED",
        ),
        at=cancel_at,
    )
    horizon_at = NOW + timedelta(hours=1)
    horizon = build(
        event_name=OUTCOME_EVIDENCE_EVENT,
        logical_event_key="horizon|alpha-eurusd|3600",
        payload=HorizonObservationEvidenceV1(
            payload_type="horizon-observation-evidence.v1",
            alpha_id="alpha:eurusd:20260824T090000Z",
            symbol="EURUSD",
            observation_kind="MARKET_HORIZON_SNAPSHOT",
            horizon_policy_version="wolf15.horizon-observation.v1",
            horizon_seconds=3600,
            reference_price=Decimal("1.10250000"),
            observed_price=Decimal("1.10400000"),
            observed_at_utc=horizon_at,
        ),
        at=horizon_at,
        refs=(
            direct_ref("WOLF15_ALPHA", "alpha:eurusd:20260824T090000Z"),
            direct_ref("WOLF15_MARKET_OBSERVATION", "market:eurusd:20260824T100000Z"),
        ),
    )
    return {
        "alpha_decision.canonical.json": alpha_first,
        "alpha_decision_retry.canonical.json": alpha_first,
        "alpha_abstention_chain_2.canonical.json": alpha_second,
        "alpha_ancestry_manifest.canonical.json": ancestry_event,
        "outcome_full_fill.canonical.json": full,
        "outcome_partial_fill.canonical.json": partial,
        "outcome_reject.canonical.json": reject,
        "outcome_cancel.canonical.json": cancel,
        "outcome_horizon_observation.canonical.json": horizon,
    }


def _rehash(raw: dict[str, Any]) -> None:
    raw["integrity"]["payload_hash"] = alpha_learning_sha256(raw["payload"])
    raw["integrity"]["envelope_hash"] = alpha_learning_envelope_hash(raw)


def negative_documents(alpha: AlphaLearningEnvelopeV1) -> dict[str, tuple[bytes, str]]:
    base = alpha.model_dump(mode="json")
    result: dict[str, tuple[bytes, str]] = {}

    def add(name: str, raw: dict[str, Any], category: str, *, rehash: bool = True) -> None:
        if rehash:
            _rehash(raw)
        result[name] = (canonical_alpha_learning_json_bytes(raw), category)

    unknown_event = copy.deepcopy(base)
    unknown_event["contract"]["event_name"] = "wolf15.unknown.exported.v1"
    unknown_event["contract"]["schema_id"] = "urn:wolf15:wla:schema:unknown:v1"
    unknown_event["identity"]["event_id"] = str(
        alpha_learning_event_id(
            event_name="wolf15.unknown.exported.v1",
            event_version=1,
            source_system="WOLF15",
            logical_event_key=unknown_event["identity"]["logical_event_key"],
        )
    )
    add("unknown_event_name.json", unknown_event, "UNKNOWN_EVENT")

    unknown_payload = copy.deepcopy(base)
    unknown_payload["payload"]["payload_type"] = "unknown-alpha-fact.v1"
    add("unknown_fact_type.json", unknown_payload, "UNKNOWN_PAYLOAD")

    extra_root = copy.deepcopy(base)
    extra_root["runtime_registration"] = False
    add("extra_root_field.json", extra_root, "EXTRA_FIELD")

    extra_nested = copy.deepcopy(base)
    extra_nested["payload"]["execution_command"] = {"action": "BUY"}
    add("unknown_nested_payload_field.json", extra_nested, "UNKNOWN_NESTED_FIELD")

    safety = copy.deepcopy(base)
    safety["safety"]["can_execute"] = True
    add("safety_escalation.json", safety, "SAFETY_ESCALATION")

    missing_safety = copy.deepcopy(base)
    del missing_safety["safety"]["can_self_promote"]
    add("missing_safety_invariant.json", missing_safety, "MISSING_SAFETY")

    consumer_time = copy.deepcopy(base)
    consumer_time["timing"]["ingested_at_utc"] = "2026-08-24T09:00:01Z"
    add("fabricated_consumer_timestamp.json", consumer_time, "CONSUMER_TIME")

    authority = copy.deepcopy(base)
    authority["authority"]["source_authority_class"] = "WOLF15_SOURCE_OUTCOME_EVIDENCE"
    add("authority_event_mismatch.json", authority, "AUTHORITY_MISMATCH")

    mismatch = copy.deepcopy(base)
    mismatch["contract"]["event_name"] = OUTCOME_EVIDENCE_EVENT
    mismatch["contract"]["schema_id"] = OUTCOME_EVIDENCE_SCHEMA_ID
    mismatch["authority"]["source_authority_class"] = "WOLF15_SOURCE_OUTCOME_EVIDENCE"
    mismatch["identity"]["event_id"] = str(
        alpha_learning_event_id(
            event_name=OUTCOME_EVIDENCE_EVENT,
            event_version=1,
            source_system="WOLF15",
            logical_event_key=mismatch["identity"]["logical_event_key"],
        )
    )
    add("event_payload_mismatch.json", mismatch, "EVENT_PAYLOAD_MISMATCH")

    conflict = copy.deepcopy(base)
    conflict["payload"]["decision"] = "SELL"
    add("same_id_conflicting_content.json", conflict, "HASH_CONFLICT", rehash=False)

    forged = copy.deepcopy(base)
    forged["payload"]["decision"] = "SELL"
    forged["payload"]["decision_reason_codes"] = ["CANONICAL_POLICY_PASS", "FORGED_DIRECTION"]
    add("forged_payload_recomputed_hash.json", forged, "PRODUCER_SIGNATURE_INVALID")

    unknown_key = copy.deepcopy(base)
    unknown_key["producer_authentication"]["key_id"] = "wolf15.unknown.fixture.ed25519.v1"
    add("unknown_producer_key.json", unknown_key, "UNKNOWN_PRODUCER_KEY")

    invalid_signature = copy.deepcopy(base)
    invalid_signature["producer_authentication"]["signature"] = PLACEHOLDER_SIGNATURE
    add("invalid_producer_signature.json", invalid_signature, "PRODUCER_SIGNATURE_INVALID", rehash=False)

    wrong_domain = copy.deepcopy(base)
    wrong_domain["producer_authentication"]["signature_domain"] = "WOLF15_EXECUTION_COMMAND_V1"
    add("wrong_signature_domain.json", wrong_domain, "WRONG_SIGNATURE_DOMAIN")

    inversion = copy.deepcopy(base)
    inversion["timing"]["observed_at_utc"] = "2026-08-24T08:59:59Z"
    add("clock_inversion.json", inversion, "CLOCK_INVERSION")

    unavailable = copy.deepcopy(base)
    unavailable["source"]["code_revision"] = "UNAVAILABLE"
    add("unavailable_revision_marked_valid.json", unavailable, "UNAVAILABLE_AS_VALID")

    noncanonical = json.dumps(base, ensure_ascii=False, indent=2, sort_keys=False).encode("utf-8")
    result["noncanonical_bytes.json"] = (noncanonical, "NONCANONICAL_BYTES")

    canonical_text = canonical_alpha_learning_json_bytes(base).decode("utf-8")
    duplicate_contract = json.dumps(base["contract"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    duplicate = (canonical_text[:-1] + ',"contract":' + duplicate_contract + "}").encode("utf-8")
    result["duplicate_json_key.json"] = (duplicate, "DUPLICATE_KEY")
    return result


def fixture_documents() -> tuple[dict[str, bytes], dict[str, Any]]:
    positives = positive_envelopes()
    documents: dict[str, bytes] = {}
    manifest: dict[str, Any] = {
        "schema": "wolf15.wla01.fixture-manifest.v1",
        "canonical_storage": "canonical-json-bytes-plus-lf",
        "positive": {},
        "negative": {},
    }
    for name, envelope in sorted(positives.items()):
        relative = f"positive/{name}"
        content = canonical_alpha_learning_json_bytes(envelope) + b"\n"
        documents[relative] = content
        manifest["positive"][relative] = {
            "file_sha256": hashlib.sha256(content).hexdigest(),
            "event_id": str(envelope.identity.event_id),
            "payload_hash": envelope.integrity.payload_hash,
            "envelope_hash": envelope.integrity.envelope_hash,
            "producer_key_id": envelope.producer_authentication.key_id,
            "producer_signature": envelope.producer_authentication.signature,
        }

    alpha = positives["alpha_decision.canonical.json"]
    for name, (content_without_required_lf, category) in sorted(negative_documents(alpha).items()):
        relative = f"negative/{name}"
        content = content_without_required_lf + b"\n"
        documents[relative] = content
        manifest["negative"][relative] = {
            "file_sha256": hashlib.sha256(content).hexdigest(),
            "expected_category": category,
        }
    documents["manifest.json"] = canonical_alpha_learning_json_bytes(manifest) + b"\n"
    return documents, manifest


def write_fixtures(root: Path = FIXTURE_ROOT) -> None:
    documents, _ = fixture_documents()
    for relative, content in documents.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def schema_bytes() -> bytes:
    schema = AlphaLearningEnvelopeV1.model_json_schema()
    schema["$id"] = "urn:wolf15:wla:schema:alpha-learning-envelope:v1"
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return canonical_alpha_learning_json_bytes(schema) + b"\n"


def write_schema(path: Path = SCHEMA_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(schema_bytes())


if __name__ == "__main__":
    write_fixtures()
    write_schema()
