"""WLA-01 contract-only gates for AlphaLearningEnvelopeV1."""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from contracts.alpha_learning_envelope_v1 import (
    ALPHA_FACT_EVENT,
    ALPHA_LEARNING_SIGNATURE_DOMAIN,
    MAX_CANONICAL_ENVELOPE_BYTES,
    AcceptedAlphaLearningEnvelopeV1,
    AlphaLearningEnvelopeV1,
    AncestryManifestRefV1,
    CausalityV1,
    ProducerAuthenticationError,
    ProducerKeyBindingV1,
    QualityV1,
    SourceIdentityV1,
    StreamPositionV1,
    alpha_learning_envelope_hash,
    alpha_learning_sha256,
    alpha_learning_signature_preimage,
    authenticate_alpha_learning_envelope_v1,
    build_alpha_learning_envelope_v1,
    canonical_alpha_learning_json_bytes,
    parse_alpha_learning_envelope_v1,
)
from tests.wla01_contract.fixture_factory import (
    ALPHA_TEST_PRODUCER_KEY_ID,
    CORRELATION_ID,
    FIXTURE_ROOT,
    NOW,
    PLACEHOLDER_SIGNATURE,
    PRODUCER_RUN_ID,
    SCHEMA_PATH,
    alpha_decision,
    direct_ref,
    first_stream,
    fixture_documents,
    positive_envelopes,
    producer_key_binding,
    producer_key_registry,
    schema_bytes,
    sign_fixture_envelope,
    source,
    timing,
    valid_quality,
)

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "contracts" / "alpha_learning_envelope_v1.py"


def _stored_contract_bytes(path: Path) -> bytes:
    content = path.read_bytes()
    assert content.endswith(b"\n")
    return content[:-1]


def _authenticated_fixture(path: Path) -> AcceptedAlphaLearningEnvelopeV1:
    untrusted = parse_alpha_learning_envelope_v1(_stored_contract_bytes(path))
    assert untrusted.trust_status == "UNTRUSTED"
    return authenticate_alpha_learning_envelope_v1(
        untrusted,
        key_registry=producer_key_registry(),
        known_event_hashes={},
    )


def test_generated_schema_and_fixtures_are_exactly_reproducible() -> None:
    documents, manifest = fixture_documents()
    assert len(manifest["positive"]) == 9
    assert len(manifest["negative"]) == 18
    for relative, expected in documents.items():
        assert (FIXTURE_ROOT / relative).read_bytes() == expected
    assert SCHEMA_PATH.read_bytes() == schema_bytes()


def test_fixture_manifest_hashes_bind_every_document() -> None:
    manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    for section in ("positive", "negative"):
        for relative, evidence in manifest[section].items():
            actual = hashlib.sha256((FIXTURE_ROOT / relative).read_bytes()).hexdigest()
            assert actual == evidence["file_sha256"]


def test_every_positive_fixture_parses_and_hashes_match() -> None:
    manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    for relative, evidence in manifest["positive"].items():
        accepted = _authenticated_fixture(FIXTURE_ROOT / relative)
        assert accepted.trust_status == "ACCEPTED"
        envelope = accepted.envelope
        assert str(envelope.identity.event_id) == evidence["event_id"]
        assert envelope.integrity.payload_hash == evidence["payload_hash"]
        assert envelope.integrity.envelope_hash == evidence["envelope_hash"]
        assert alpha_learning_envelope_hash(envelope) == evidence["envelope_hash"]
        assert envelope.authority.source_interaction_authority == "OBSERVATIONAL_ONLY"
        assert envelope.authority.wla_decision_authority == "NONE"
        assert envelope.authority.wla_gate_authority == "NONE"
        assert envelope.safety.can_mutate_source is False
        assert envelope.safety.can_issue_verdict is False
        assert envelope.safety.can_execute is False
        assert envelope.safety.can_self_promote is False


def test_structural_parsing_is_untrusted_and_accepted_cannot_be_constructed() -> None:
    path = FIXTURE_ROOT / "positive" / "alpha_decision.canonical.json"
    untrusted = parse_alpha_learning_envelope_v1(_stored_contract_bytes(path))
    assert untrusted.trust_status == "UNTRUSTED"
    with pytest.raises(TypeError, match="only be created"):
        AcceptedAlphaLearningEnvelopeV1()
    verifier_parameters = inspect.signature(authenticate_alpha_learning_envelope_v1).parameters
    assert verifier_parameters["key_registry"].default is inspect.Parameter.empty
    assert verifier_parameters["known_event_hashes"].default is inspect.Parameter.empty


def test_valid_ed25519_signature_is_the_only_path_to_accepted() -> None:
    accepted = _authenticated_fixture(FIXTURE_ROOT / "positive" / "alpha_decision.canonical.json")
    assert accepted.trust_status == "ACCEPTED"
    assert accepted.authenticated_key_id == ALPHA_TEST_PRODUCER_KEY_ID
    assert accepted.authenticated_producer_role == "WOLF15_CANONICAL_ALPHA"
    protected_attribute = "_envelope"
    with pytest.raises(TypeError, match="immutable"):
        setattr(accepted, protected_attribute, positive_envelopes()["alpha_decision.canonical.json"])


@pytest.mark.parametrize(
    ("registry", "message"),
    [
        ({}, "not allowlisted"),
        (
            {ALPHA_TEST_PRODUCER_KEY_ID: producer_key_binding(status="REVOKED")},
            "revoked",
        ),
        (
            {
                ALPHA_TEST_PRODUCER_KEY_ID: producer_key_binding(
                    signature_domain="WOLF15_EXECUTION_COMMAND_V1"
                )
            },
            "domain",
        ),
        (
            {
                ALPHA_TEST_PRODUCER_KEY_ID: producer_key_binding(
                    producer_role="WOLF15_SOURCE_OUTCOME_EVIDENCE"
                )
            },
            "role",
        ),
        (
            {
                ALPHA_TEST_PRODUCER_KEY_ID: producer_key_binding(
                    source_service="other-source-export"
                )
            },
            "source service",
        ),
    ],
)
def test_unknown_revoked_and_mismatched_key_bindings_fail_closed(
    registry: dict[str, ProducerKeyBindingV1],
    message: str,
) -> None:
    path = FIXTURE_ROOT / "positive" / "alpha_decision.canonical.json"
    untrusted = parse_alpha_learning_envelope_v1(_stored_contract_bytes(path))
    with pytest.raises(ProducerAuthenticationError, match=message):
        authenticate_alpha_learning_envelope_v1(
            untrusted,
            key_registry=registry,
            known_event_hashes={},
        )


@pytest.mark.parametrize(
    "name",
    ["forged_payload_recomputed_hash.json", "invalid_producer_signature.json"],
)
def test_forged_payload_recomputed_hash_and_invalid_signature_are_rejected(name: str) -> None:
    path = FIXTURE_ROOT / "negative" / name
    untrusted = parse_alpha_learning_envelope_v1(_stored_contract_bytes(path))
    assert untrusted.trust_status == "UNTRUSTED"
    with pytest.raises(ProducerAuthenticationError, match="signature is invalid"):
        authenticate_alpha_learning_envelope_v1(
            untrusted,
            key_registry=producer_key_registry(),
            known_event_hashes={},
        )


def test_same_event_id_with_different_validly_signed_content_is_rejected() -> None:
    original = positive_envelopes()["alpha_decision.canonical.json"]
    raw = original.model_dump(mode="json")
    raw["payload"]["decision"] = "SELL"
    raw["payload"]["decision_reason_codes"] = ["CANONICAL_POLICY_PASS", "SIGNED_CONFLICT"]
    raw["integrity"]["payload_hash"] = alpha_learning_sha256(raw["payload"])
    raw["producer_authentication"]["signature"] = PLACEHOLDER_SIGNATURE
    raw["integrity"]["envelope_hash"] = alpha_learning_envelope_hash(raw)
    conflicting = sign_fixture_envelope(
        AlphaLearningEnvelopeV1.model_validate_json(canonical_alpha_learning_json_bytes(raw))
    )
    untrusted = parse_alpha_learning_envelope_v1(canonical_alpha_learning_json_bytes(conflicting))

    with pytest.raises(ProducerAuthenticationError, match="already bound to different content"):
        authenticate_alpha_learning_envelope_v1(
            untrusted,
            key_registry=producer_key_registry(),
            known_event_hashes={str(original.identity.event_id): original.integrity.envelope_hash},
        )


def test_signature_preimage_binds_the_entire_canonical_unsigned_envelope() -> None:
    envelope = positive_envelopes()["alpha_decision.canonical.json"]
    raw = envelope.model_dump(mode="json")
    baseline = alpha_learning_signature_preimage(raw)
    mutations = (
        ("contract", "event_name", "wolf15.outcome-evidence.exported.v1"),
        ("contract", "schema_id", "urn:wolf15:wla:schema:changed:v1"),
        ("identity", "event_id", "00000000-0000-0000-0000-000000000000"),
        ("source", "deployment_id", "different-deployment"),
        ("authority", "source_authority_class", "WOLF15_SOURCE_OUTCOME_EVIDENCE"),
        ("producer_authentication", "key_id", "wolf15.other.fixture.ed25519.v1"),
        ("payload", "decision", "SELL"),
        ("integrity", "payload_hash", "sha256:" + "0" * 64),
    )
    for section, field, replacement in mutations:
        changed = json.loads(json.dumps(raw))
        changed[section][field] = replacement
        assert alpha_learning_signature_preimage(changed) != baseline

    signature_only = json.loads(json.dumps(raw))
    signature_only["producer_authentication"]["signature"] = PLACEHOLDER_SIGNATURE
    assert alpha_learning_signature_preimage(signature_only) == baseline


def test_every_negative_fixture_fails_closed() -> None:
    manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    observed_categories: set[str] = set()
    for relative, evidence in manifest["negative"].items():
        with pytest.raises((ValueError, ValidationError)):
            untrusted = parse_alpha_learning_envelope_v1(_stored_contract_bytes(FIXTURE_ROOT / relative))
            authenticate_alpha_learning_envelope_v1(
                untrusted,
                key_registry=producer_key_registry(),
                known_event_hashes={},
            )
        observed_categories.add(evidence["expected_category"])
    assert observed_categories == {
        "AUTHORITY_MISMATCH",
        "CLOCK_INVERSION",
        "CONSUMER_TIME",
        "DUPLICATE_KEY",
        "EVENT_PAYLOAD_MISMATCH",
        "EXTRA_FIELD",
        "HASH_CONFLICT",
        "PRODUCER_SIGNATURE_INVALID",
        "MISSING_SAFETY",
        "NONCANONICAL_BYTES",
        "SAFETY_ESCALATION",
        "UNAVAILABLE_AS_VALID",
        "UNKNOWN_PRODUCER_KEY",
        "UNKNOWN_EVENT",
        "UNKNOWN_NESTED_FIELD",
        "UNKNOWN_PAYLOAD",
        "WRONG_SIGNATURE_DOMAIN",
    }


def test_identical_retry_has_identical_identity_and_bytes() -> None:
    original = (FIXTURE_ROOT / "positive" / "alpha_decision.canonical.json").read_bytes()
    retry = (FIXTURE_ROOT / "positive" / "alpha_decision_retry.canonical.json").read_bytes()
    assert retry == original


def test_same_identity_with_different_content_is_detectable_conflict() -> None:
    first = positive_envelopes()["alpha_decision.canonical.json"]
    changed_payload = alpha_decision().model_copy(
        update={
            "decision": "SELL",
            "decision_reason_codes": ("CANONICAL_POLICY_PASS", "DIRECTION_CHANGED"),
        }
    )
    changed = build_alpha_learning_envelope_v1(
        event_name=ALPHA_FACT_EVENT,
        logical_event_key=first.identity.logical_event_key,
        correlation_id=CORRELATION_ID,
        causation_id=None,
        direct_source_refs=first.causality.direct_source_refs,
        ancestry_manifest=None,
        stream=first.stream,
        source=source(),
        timing=timing(),
        quality=valid_quality(),
        producer_run_id=PRODUCER_RUN_ID,
        producer_key_id=ALPHA_TEST_PRODUCER_KEY_ID,
        producer_signature=PLACEHOLDER_SIGNATURE,
        payload=changed_payload,
    )
    assert changed.identity.event_id == first.identity.event_id
    assert changed.integrity.payload_hash != first.integrity.payload_hash
    assert changed.integrity.envelope_hash != first.integrity.envelope_hash


def test_event_identity_survives_deployment_restart() -> None:
    first = positive_envelopes()["alpha_decision.canonical.json"]
    restarted_source = source().model_copy(update={"deployment_id": "fixture-deployment-restart"})
    restarted = build_alpha_learning_envelope_v1(
        event_name=ALPHA_FACT_EVENT,
        logical_event_key=first.identity.logical_event_key,
        correlation_id=CORRELATION_ID,
        causation_id=None,
        direct_source_refs=first.causality.direct_source_refs,
        ancestry_manifest=None,
        stream=first.stream,
        source=restarted_source,
        timing=timing(),
        quality=valid_quality(),
        producer_run_id=PRODUCER_RUN_ID,
        producer_key_id=ALPHA_TEST_PRODUCER_KEY_ID,
        producer_signature=PLACEHOLDER_SIGNATURE,
        payload=alpha_decision(),
    )
    assert restarted.identity.event_id == first.identity.event_id
    assert restarted.integrity.envelope_hash != first.integrity.envelope_hash


def test_stream_chain_binds_the_immediate_predecessor() -> None:
    fixtures = positive_envelopes()
    first = fixtures["alpha_decision.canonical.json"]
    second = fixtures["alpha_abstention_chain_2.canonical.json"]
    assert second.stream.previous_stream_sequence == first.stream.stream_sequence
    assert second.stream.previous_event_hash == first.integrity.envelope_hash
    with pytest.raises(ValidationError, match="immediate predecessor"):
        StreamPositionV1(
            stream_id="alpha:EURUSD",
            stream_sequence=3,
            previous_stream_sequence=1,
            previous_event_hash=first.integrity.envelope_hash,
            ordering_scope="SOURCE_STREAM",
        )


def test_large_ancestry_is_sealed_not_inlined() -> None:
    envelope = positive_envelopes()["alpha_ancestry_manifest.canonical.json"]
    assert envelope.causality.direct_source_refs == ()
    assert envelope.causality.ancestry_manifest is not None
    assert envelope.causality.ancestry_manifest.event_count == 33
    with pytest.raises(ValidationError, match="event_count"):
        AncestryManifestRefV1(
            manifest_id="manifest:invalid",
            covered_sequence_start=1,
            covered_sequence_end=34,
            event_count=33,
            integrity_root="sha256:" + "a" * 64,
        )


def test_direct_refs_are_bounded_sorted_and_unique() -> None:
    ref = direct_ref("WOLF15_SOURCE_RECORD", "source:1")
    with pytest.raises(ValidationError, match="sorted and unique"):
        CausalityV1(
            correlation_id=CORRELATION_ID,
            causation_id=None,
            direct_source_refs=(ref, ref),
            ancestry_manifest=None,
        )
    with pytest.raises(ValidationError):
        CausalityV1(
            correlation_id=CORRELATION_ID,
            causation_id=None,
            direct_source_refs=tuple(
                direct_ref("WOLF15_SOURCE_RECORD", f"source:{index:02d}") for index in range(33)
            ),
            ancestry_manifest=None,
        )


def test_unavailable_revision_is_preserved_only_as_quarantined() -> None:
    unavailable_source = SourceIdentityV1(
        source_system="WOLF15",
        source_service="canonical-alpha-export",
        code_revision="UNAVAILABLE",
        deployment_id="fixture-deployment",
        policy_version="wolf15.alpha-export.v1",
        config_version="wolf15.fixture-config.v1",
    )
    args = {
        "event_name": ALPHA_FACT_EVENT,
        "logical_event_key": "alpha|unavailable-revision",
        "correlation_id": CORRELATION_ID,
        "causation_id": None,
        "direct_source_refs": (direct_ref("WOLF15_SOURCE_RECORD", "source:unavailable"),),
        "ancestry_manifest": None,
        "stream": first_stream("alpha:unavailable"),
        "source": unavailable_source,
        "timing": timing(),
        "producer_run_id": PRODUCER_RUN_ID,
        "producer_key_id": ALPHA_TEST_PRODUCER_KEY_ID,
        "producer_signature": PLACEHOLDER_SIGNATURE,
        "payload": alpha_decision(),
    }
    with pytest.raises(ValidationError, match="quality reasons"):
        build_alpha_learning_envelope_v1(quality=valid_quality(), **args)

    quarantined = build_alpha_learning_envelope_v1(
        quality=QualityV1(
            evidence_status="QUARANTINED",
            reason_codes=("SOURCE_REVISION_UNAVAILABLE",),
            missing_fields=(),
            uncertainty_flags=("SOURCE_REVISION_UNAVAILABLE",),
            correction_of_event_id=None,
            supersedes_event_id=None,
            invalidates_event_id=None,
        ),
        **args,
    )
    assert quarantined.quality.evidence_status == "QUARANTINED"


@pytest.mark.parametrize(
    ("clock_status", "reason"),
    [("DEGRADED", "SOURCE_CLOCK_DEGRADED"), ("UNKNOWN", "SOURCE_CLOCK_UNKNOWN")],
)
def test_unhealthy_clock_requires_matching_quarantine(clock_status: str, reason: str) -> None:
    unhealthy_timing = timing().model_copy(update={"clock_status": clock_status})
    with pytest.raises(ValidationError, match="quality reasons"):
        build_alpha_learning_envelope_v1(
            event_name=ALPHA_FACT_EVENT,
            logical_event_key=f"alpha|clock|{clock_status.lower()}",
            correlation_id=CORRELATION_ID,
            causation_id=None,
            direct_source_refs=(direct_ref("WOLF15_SOURCE_RECORD", f"source:{clock_status}"),),
            ancestry_manifest=None,
            stream=first_stream(f"alpha:clock:{clock_status}"),
            source=source(),
            timing=unhealthy_timing,
            quality=valid_quality(),
            producer_run_id=PRODUCER_RUN_ID,
            producer_key_id=ALPHA_TEST_PRODUCER_KEY_ID,
            producer_signature=PLACEHOLDER_SIGNATURE,
            payload=alpha_decision(),
        )
    assert reason in {"SOURCE_CLOCK_DEGRADED", "SOURCE_CLOCK_UNKNOWN"}


def test_outcome_evidence_never_contains_a_derived_label() -> None:
    forbidden = {"outcome", "outcome_label", "win", "loss", "profit", "target"}
    for path in sorted((FIXTURE_ROOT / "positive").glob("outcome_*.json")):
        envelope = _authenticated_fixture(path).envelope
        assert not forbidden.intersection(envelope.payload.model_fields_set)


def test_source_profile_rejects_consumer_owned_timestamps() -> None:
    schema_text = SCHEMA_PATH.read_text(encoding="utf-8")
    assert "first_received_at_utc" not in schema_text
    assert "ingested_at_utc" not in schema_text
    assert "learning_available_at_utc" not in schema_text


def test_reference_parser_rejects_noncanonical_or_unsafe_bytes() -> None:
    valid = _stored_contract_bytes(FIXTURE_ROOT / "positive" / "alpha_decision.canonical.json")
    with pytest.raises(ValueError, match="byte length"):
        parse_alpha_learning_envelope_v1(b"")
    with pytest.raises(ValueError, match="byte length"):
        parse_alpha_learning_envelope_v1(b"{" + b" " * MAX_CANONICAL_ENVELOPE_BYTES + b"}")
    with pytest.raises(ValueError, match="UTF-8"):
        parse_alpha_learning_envelope_v1(b"\xff")
    with pytest.raises(ValueError, match="root"):
        parse_alpha_learning_envelope_v1(b"[]")
    with pytest.raises(ValueError, match="canonical"):
        parse_alpha_learning_envelope_v1(valid + b"\n")
    with pytest.raises(ValueError, match="strict JSON"):
        parse_alpha_learning_envelope_v1(valid[:-1] + b',"x":NaN}')


def test_required_false_invariants_do_not_coerce_integer_zero() -> None:
    raw = json.loads(_stored_contract_bytes(FIXTURE_ROOT / "positive" / "alpha_decision.canonical.json"))
    raw["safety"]["can_execute"] = 0
    raw["integrity"]["envelope_hash"] = alpha_learning_envelope_hash(raw)
    with pytest.raises(ValidationError):
        AlphaLearningEnvelopeV1.model_validate_json(canonical_alpha_learning_json_bytes(raw))


def test_json_schema_is_closed_and_identifies_draft_2020_12() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == "urn:wolf15:wla:schema:alpha-learning-envelope:v1"
    assert "producer_authentication" in schema["required"]
    authentication_schema = schema["$defs"]["ProducerAuthenticationV1"]
    assert authentication_schema["properties"]["algorithm"]["const"] == "ED25519"
    assert authentication_schema["properties"]["signature_domain"]["const"] == ALPHA_LEARNING_SIGNATURE_DOMAIN
    payload_schema = schema["properties"]["payload"]
    assert payload_schema["discriminator"]["propertyName"] == "payload_type"
    assert set(payload_schema["discriminator"]["mapping"]) == {
        "canonical-alpha-decision.v1",
        "canonical-alpha-abstention.v1",
        "fill-evidence.v1",
        "partial-fill-evidence.v1",
        "reject-evidence.v1",
        "cancel-evidence.v1",
        "horizon-observation-evidence.v1",
    }


def test_contract_has_no_runtime_transport_or_storage_imports() -> None:
    tree = ast.parse(CONTRACT_PATH.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
    assert imported_roots <= {
        "__future__",
        "base64",
        "binascii",
        "collections",
        "cryptography",
        "datetime",
        "decimal",
        "hashlib",
        "json",
        "pydantic",
        "typing",
        "uuid",
    }
    assert not {
        "MetaTrader5",
        "alembic",
        "asyncio",
        "httpx",
        "os",
        "psycopg",
        "redis",
        "requests",
        "socket",
        "sqlalchemy",
    }.intersection(imported_roots)


def test_private_signing_key_exists_only_in_test_fixture_code() -> None:
    contract_text = CONTRACT_PATH.read_text(encoding="utf-8")
    schema_text = SCHEMA_PATH.read_text(encoding="utf-8")
    assert "Ed25519PrivateKey" not in contract_text
    assert "TEST_PRIVATE_KEY_SEED" not in contract_text
    assert "private_key" not in schema_text


def test_contract_is_not_auto_registered_or_imported_by_package() -> None:
    package_init = (CONTRACT_PATH.parent / "__init__.py").read_text(encoding="utf-8")
    assert "alpha_learning_envelope_v1" not in package_init
    assert "AlphaLearningEnvelopeV1" not in package_init


def test_payload_occurrence_time_must_match_source_timing() -> None:
    with pytest.raises(ValidationError, match="occurrence time"):
        build_alpha_learning_envelope_v1(
            event_name=ALPHA_FACT_EVENT,
            logical_event_key="alpha|time-mismatch",
            correlation_id=UUID("65f57089-946a-525d-abd2-950206f1c9c2"),
            causation_id=None,
            direct_source_refs=(direct_ref("WOLF15_SOURCE_RECORD", "source:time-mismatch"),),
            ancestry_manifest=None,
            stream=first_stream("alpha:time-mismatch"),
            source=source(),
            timing=timing(NOW + timedelta(seconds=1)),
            quality=valid_quality(),
            producer_run_id=PRODUCER_RUN_ID,
            producer_key_id=ALPHA_TEST_PRODUCER_KEY_ID,
            producer_signature=PLACEHOLDER_SIGNATURE,
            payload=alpha_decision(NOW),
        )
