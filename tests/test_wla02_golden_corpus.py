from __future__ import annotations

import ast
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from contracts.alpha_learning_envelope_v1 import (
    ALPHA_LEARNING_SIGNATURE_DOMAIN,
    CanonicalAlphaAbstentionFactV1,
    CanonicalAlphaDecisionFactV1,
    FillOutcomeEvidenceV1,
    HorizonObservationEvidenceV1,
    ProducerAuthenticationError,
    ProducerKeyBindingV1,
    canonical_alpha_learning_json_bytes,
)
from contracts.wla02_golden_corpus import (
    AmbiguousCorpusError,
    CorrectionLineageError,
    CounterfactualMarketOutcomeSourceV1,
    DecisionSourceV1,
    FutureLeakageError,
    GoldenCorpusEntryV1,
    OutcomeUnavailableError,
    RealizedBrokerOutcomeSourceV1,
    UnavailableOutcomeSourceV1,
    map_decision_source_v1,
    map_outcome_source_v1,
    replay_golden_corpus_v1,
)
from tests.wla01_contract.fixture_factory import producer_key_binding, producer_key_registry
from tests.wla02_golden.fixture_factory import (
    FIXTURE_ROOT,
    NOW,
    _entry,
    counterfactual_source,
    decision_source,
    future_leakage_canary,
    generated_artifacts,
    positive_entries,
    realized_source,
    unavailable_sources,
    verify_committed_fixtures,
)


def _cutoffs(entries: dict[str, GoldenCorpusEntryV1]) -> tuple[datetime, datetime]:
    return (
        max(entry.valid_at_utc for entry in entries.values()),
        max(entry.known_at_utc for entry in entries.values()),
    )


def _replay(entries: dict[str, GoldenCorpusEntryV1]):
    valid_cutoff, knowledge_cutoff = _cutoffs(entries)
    return replay_golden_corpus_v1(
        tuple(entries.values()),
        valid_time_cutoff_utc=valid_cutoff,
        knowledge_time_cutoff_utc=knowledge_cutoff,
        key_registry=producer_key_registry(),
    )


@pytest.mark.parametrize(
    ("disposition", "execution_valid", "payload_type", "mapped_value"),
    [
        ("BUY", True, CanonicalAlphaDecisionFactV1, "BUY"),
        ("SELL", True, CanonicalAlphaDecisionFactV1, "SELL"),
        ("WAIT", False, CanonicalAlphaDecisionFactV1, "WAIT"),
        ("HOLD", False, CanonicalAlphaAbstentionFactV1, "RISK_BLOCKED"),
        ("NO_TRADE", False, CanonicalAlphaAbstentionFactV1, "POLICY_BLOCKED"),
        ("CONFLICT", False, CanonicalAlphaAbstentionFactV1, "SOURCE_UNKNOWN"),
    ],
)
def test_decision_mapper_has_closed_status_coverage(
    disposition: str,
    execution_valid: bool,
    payload_type: type,
    mapped_value: str,
) -> None:
    source = decision_source(disposition, at=NOW, source_valid_for_execution=execution_valid)
    payload = map_decision_source_v1(source)
    assert isinstance(payload, payload_type)
    actual = payload.decision if isinstance(payload, CanonicalAlphaDecisionFactV1) else payload.abstention_kind
    assert actual == mapped_value
    if disposition in {"WAIT", "HOLD", "NO_TRADE", "CONFLICT"}:
        assert payload.source_valid_for_execution is False


def test_non_action_decision_cannot_be_execution_valid() -> None:
    raw = decision_source("WAIT", at=NOW).model_dump(mode="python")
    raw["source_valid_for_execution"] = True
    with pytest.raises(ValidationError, match="cannot be source-valid"):
        DecisionSourceV1.model_validate(raw)


@pytest.mark.parametrize("outcome_kind", ["EXECUTED", "REJECTED", "EXPIRED"])
def test_realized_outcome_mapper_coverage(outcome_kind: str) -> None:
    source = realized_source(outcome_kind, at=NOW)
    payload = map_outcome_source_v1(source)
    assert source.evidence_class == "REALIZED_BROKER"
    assert not isinstance(payload, HorizonObservationEvidenceV1)
    if outcome_kind == "EXECUTED":
        assert isinstance(payload, FillOutcomeEvidenceV1)
        assert payload.finality == "FULL"


def test_counterfactual_is_typed_separately_from_realized() -> None:
    source = counterfactual_source("WAIT", at=NOW)
    payload = map_outcome_source_v1(source)
    assert isinstance(payload, HorizonObservationEvidenceV1)
    assert source.evidence_class == "COUNTERFACTUAL_MARKET"

    mixed = source.model_dump(mode="python")
    mixed["order_id"] = "order-forbidden"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CounterfactualMarketOutcomeSourceV1.model_validate(mixed)

    wrong_class = realized_source("EXECUTED", at=NOW).model_dump(mode="python")
    wrong_class["evidence_class"] = "COUNTERFACTUAL_MARKET"
    with pytest.raises(ValidationError, match="REALIZED_BROKER"):
        RealizedBrokerOutcomeSourceV1.model_validate(wrong_class)


@pytest.mark.parametrize("name", ["censored", "missing"])
def test_censored_or_missing_input_never_becomes_outcome_evidence(name: str) -> None:
    source = unavailable_sources()[name]
    with pytest.raises(OutcomeUnavailableError, match="cannot be promoted"):
        map_outcome_source_v1(source)


def test_unavailable_source_requires_explicit_missingness() -> None:
    raw = unavailable_sources()["missing"].model_dump(mode="python")
    raw["missing_fields"] = ()
    with pytest.raises(ValidationError, match="at least 1 item"):
        UnavailableOutcomeSourceV1.model_validate(raw)


def test_committed_fixtures_are_exactly_reproducible_and_hash_bound() -> None:
    first = generated_artifacts()
    second = generated_artifacts()
    assert first == second
    verify_committed_fixtures()

    manifest = json.loads(first["manifest.json"])
    for artifact in manifest["artifacts"]:
        expected = "sha256:" + hashlib.sha256(first[artifact["path"]]).hexdigest()
        assert artifact["sha256"] == expected
    assert manifest["positive_entry_count"] == 13
    assert manifest["realized_and_counterfactual_are_distinct"] is True
    assert manifest["runtime_authority"] == "NONE"


def test_replay_is_authenticated_deterministic_and_order_independent() -> None:
    entries = positive_entries()
    first = _replay(entries)
    valid_cutoff, knowledge_cutoff = _cutoffs(entries)
    second = replay_golden_corpus_v1(
        tuple(reversed(tuple(entries.values()))),
        valid_time_cutoff_utc=valid_cutoff,
        knowledge_time_cutoff_utc=knowledge_cutoff,
        key_registry=producer_key_registry(),
    )
    assert first == second
    assert len(first.history_event_ids) == 13
    assert len(first.effective_event_ids) == 12

    manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert first.history_hash == manifest["history_hash"]
    assert first.effective_hash == manifest["effective_hash"]


def test_future_knowledge_canary_fails_closed() -> None:
    entries = positive_entries()
    canary = future_leakage_canary(entries)
    valid_cutoff, knowledge_cutoff = _cutoffs(entries)
    with pytest.raises(FutureLeakageError, match="canary.future-leakage"):
        replay_golden_corpus_v1(
            (*entries.values(), canary),
            valid_time_cutoff_utc=max(valid_cutoff, canary.valid_at_utc),
            knowledge_time_cutoff_utc=knowledge_cutoff,
            key_registry=producer_key_registry(),
        )


def test_valid_time_and_knowledge_time_cutoffs_are_separate() -> None:
    entries = positive_entries()
    _, knowledge_cutoff = _cutoffs(entries)
    replay = replay_golden_corpus_v1(
        tuple(entries.values()),
        valid_time_cutoff_utc=NOW + timedelta(minutes=2),
        knowledge_time_cutoff_utc=knowledge_cutoff,
        key_registry=producer_key_registry(),
    )
    assert replay.accepted_fixture_ids == ("decision.executed", "decision.wait", "decision.hold")


def test_entry_binds_source_snapshot_to_exact_mapped_payload() -> None:
    executed = positive_entries()["decision.executed"]
    wait_source = decision_source("WAIT", at=executed.valid_at_utc)
    raw = executed.model_dump(mode="python")
    raw["source_snapshot"] = wait_source
    raw["source_snapshot_hash"] = "sha256:" + hashlib.sha256(
        canonical_alpha_learning_json_bytes(wait_source)
    ).hexdigest()
    with pytest.raises(ValidationError, match="deterministic typed source mapping"):
        GoldenCorpusEntryV1.model_validate(raw)


def test_knowledge_time_cannot_precede_source_publication() -> None:
    entry = positive_entries()["decision.executed"]
    raw = entry.model_dump(mode="python")
    raw["known_at_utc"] = entry.valid_at_utc + timedelta(milliseconds=150)
    assert raw["known_at_utc"] < entry.envelope.timing.source_published_at_utc
    with pytest.raises(ValidationError, match="cannot precede source publication"):
        GoldenCorpusEntryV1.model_validate(raw)


def test_correction_is_append_only_history_with_one_effective_replacement() -> None:
    entries = positive_entries()
    original = entries["counterfactual.conflict"]
    correction = entries["counterfactual.conflict.correction-1"]
    replay = _replay(entries)
    original_id = original.envelope.identity.event_id
    correction_id = correction.envelope.identity.event_id
    assert original_id in replay.history_event_ids
    assert correction_id in replay.history_event_ids
    assert original_id not in replay.effective_event_ids
    assert correction_id in replay.effective_event_ids
    assert correction.correction_of_event_id == original_id


def test_correction_target_must_be_present_and_earlier() -> None:
    correction = positive_entries()["counterfactual.conflict.correction-1"]
    with pytest.raises(CorrectionLineageError, match="not an earlier"):
        replay_golden_corpus_v1(
            (correction,),
            valid_time_cutoff_utc=correction.valid_at_utc,
            knowledge_time_cutoff_utc=correction.known_at_utc,
            key_registry=producer_key_registry(),
        )


def test_correction_cannot_cross_evidence_classes() -> None:
    decision = positive_entries()["decision.executed"]
    realized = _entry(
        realized_source("EXECUTED", at=NOW + timedelta(hours=3)),
        fixture_id="realized.executed.cross-class-correction",
        case_label="EXECUTED",
        evidence_class="REALIZED_BROKER",
        known_at_utc=NOW + timedelta(hours=3, seconds=1),
        correction_of_event_id=decision.envelope.identity.event_id,
    )
    with pytest.raises(CorrectionLineageError, match="cross evidence classes"):
        replay_golden_corpus_v1(
            (decision, realized),
            valid_time_cutoff_utc=realized.valid_at_utc,
            knowledge_time_cutoff_utc=realized.known_at_utc,
            key_registry=producer_key_registry(),
        )


def test_correction_lineage_cannot_fork() -> None:
    entries = positive_entries()
    original = entries["counterfactual.conflict"]
    first_correction = entries["counterfactual.conflict.correction-1"]
    second_source = counterfactual_source(
        "CONFLICT",
        at=first_correction.valid_at_utc + timedelta(minutes=1),
        corrected=True,
    )
    fork = _entry(
        second_source,
        fixture_id="counterfactual.conflict.correction-fork",
        case_label="CONFLICT",
        evidence_class="COUNTERFACTUAL_MARKET",
        known_at_utc=first_correction.known_at_utc + timedelta(minutes=1),
        logical_event_key="wla02|counterfactual.conflict|correction-fork",
        correction_of_event_id=original.envelope.identity.event_id,
    )
    with pytest.raises(CorrectionLineageError, match="forked"):
        replay_golden_corpus_v1(
            (original, first_correction, fork),
            valid_time_cutoff_utc=fork.valid_at_utc,
            knowledge_time_cutoff_utc=fork.known_at_utc,
            key_registry=producer_key_registry(),
        )


def test_duplicate_corpus_identity_is_ambiguous() -> None:
    entry = positive_entries()["decision.wait"]
    with pytest.raises(AmbiguousCorpusError, match="duplicate fixture_id"):
        replay_golden_corpus_v1(
            (entry, entry),
            valid_time_cutoff_utc=entry.valid_at_utc,
            knowledge_time_cutoff_utc=entry.known_at_utc,
            key_registry=producer_key_registry(),
        )


@pytest.mark.parametrize("mutation", ["pretty", "timestamp_alias"])
def test_wla01_noncanonical_raw_bytes_invariant_is_inherited(mutation: str) -> None:
    entry = positive_entries()["decision.executed"]
    raw = entry.model_dump(mode="python")
    envelope = json.loads(entry.envelope_canonical_json)
    if mutation == "pretty":
        raw["envelope_canonical_json"] = json.dumps(envelope, indent=2, ensure_ascii=False)
    else:
        alias = entry.envelope_canonical_json.replace("2026-08-24T16:00:00Z", "2026-08-24T16:00:00+00:00")
        assert alias != entry.envelope_canonical_json
        raw["envelope_canonical_json"] = alias
    with pytest.raises(ValidationError, match="canonical"):
        GoldenCorpusEntryV1.model_validate(raw)


def test_replay_rejects_invalid_signature_unknown_and_revoked_keys() -> None:
    entry = positive_entries()["decision.executed"]
    raw = entry.model_dump(mode="python")
    envelope = json.loads(entry.envelope_canonical_json)
    signature = envelope["producer_authentication"]["signature"]
    envelope["producer_authentication"]["signature"] = signature[:-1] + ("A" if signature[-1] != "A" else "B")
    raw["envelope_canonical_json"] = canonical_alpha_learning_json_bytes(envelope).decode("utf-8")
    forged = GoldenCorpusEntryV1.model_validate(raw)

    with pytest.raises(ProducerAuthenticationError, match="signature is invalid"):
        replay_golden_corpus_v1(
            (forged,),
            valid_time_cutoff_utc=forged.valid_at_utc,
            knowledge_time_cutoff_utc=forged.known_at_utc,
            key_registry=producer_key_registry(),
        )

    with pytest.raises(ProducerAuthenticationError, match="not allowlisted"):
        replay_golden_corpus_v1(
            (entry,),
            valid_time_cutoff_utc=entry.valid_at_utc,
            knowledge_time_cutoff_utc=entry.known_at_utc,
            key_registry={},
        )

    key_id = entry.envelope.producer_authentication.key_id
    revoked: dict[str, ProducerKeyBindingV1] = {
        key_id: producer_key_binding(
            key_id=key_id,
            status="REVOKED",
            signature_domain=ALPHA_LEARNING_SIGNATURE_DOMAIN,
        )
    }
    with pytest.raises(ProducerAuthenticationError, match="revoked"):
        replay_golden_corpus_v1(
            (entry,),
            valid_time_cutoff_utc=entry.valid_at_utc,
            knowledge_time_cutoff_utc=entry.known_at_utc,
            key_registry=revoked,
        )


def test_every_fixture_remains_non_authoritative() -> None:
    for entry in positive_entries().values():
        envelope = entry.envelope
        assert envelope.safety.can_mutate_source is False
        assert envelope.safety.can_issue_verdict is False
        assert envelope.safety.can_execute is False
        assert envelope.safety.can_self_promote is False
        assert envelope.authority.wla_decision_authority == "NONE"
        assert envelope.authority.wla_gate_authority == "NONE"


def test_wla02_module_has_no_runtime_network_database_or_broker_imports() -> None:
    module_path = Path("contracts/wla02_golden_corpus.py")
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
    forbidden = {
        "MetaTrader5",
        "aiohttp",
        "asyncpg",
        "httpx",
        "psycopg",
        "redis",
        "requests",
        "socket",
        "sqlalchemy",
    }
    assert imported_roots.isdisjoint(forbidden)
