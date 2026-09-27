"""Policy + WOLF15_XM_30_V1 universe loading for the offline shadow harness."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from pydantic import ValidationError

from tests.shadow_harness_helpers import (
    POLICY_PATH,
    REPO_ROOT,
    broker_dry_run,
    candidate,
    load_real,
    risk_dry_run,
    tradeplan,
)
from tools.shadow_harness.captures import (
    BrokerAdaptationDryRunCapture,
    CandidateCapture,
    PricePoint,
    RiskDryRunCapture,
    TradeplanCapture,
)
from tools.shadow_harness.manifest import (
    CAPTURE_KINDS,
    GLOBAL_SCOPE_ALLOWED_CAPTURE_KINDS,
    GLOBAL_SCOPE_FORBIDDEN_CAPTURE_KINDS,
    PAIR_BINDING_REQUIRED_CAPTURE_KINDS,
    HarnessInputError,
    load_policy_bytes,
    load_symbol_universe_bytes,
    resolve_symbol_map_path,
)

SYMBOL_MAP = REPO_ROOT / "ea_interface" / "wolf15_executor" / "broker_maps" / "xmglobal-mt5-10.csv"
EA_SOURCE = REPO_ROOT / "ea_interface" / "wolf15_executor" / "Wolf15_DumbExecutor_Shadow.mq5"


def _policy_payload() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _map_lines() -> list[str]:
    return SYMBOL_MAP.read_text(encoding="utf-8-sig").splitlines()


def test_real_policy_and_universe_are_pinned_and_exactly_thirty() -> None:
    loaded, universe = load_real()
    assert loaded.policy.symbol_universe == "WOLF15_XM_30_V1"
    assert resolve_symbol_map_path(loaded, REPO_ROOT) == SYMBOL_MAP
    assert len(universe.symbols) == 30
    assert len(set(universe.symbols)) == 30
    assert universe.canonical_sha256 == loaded.policy.symbol_map_canonical_sha256
    assert universe.broker_symbol_for("XAUUSD") == "GOLD"
    assert universe.broker_symbol_for("NOTAPAIR") is None


def test_universe_matches_compiled_ea_universe() -> None:
    _, universe = load_real()
    source = EA_SOURCE.read_text(encoding="utf-8", errors="replace")
    block = re.search(r"W15_CANONICAL_SYMBOLS\[W15_SYMBOL_COUNT\]\s*=\s*\{(.*?)\};", source, re.S)
    assert block is not None
    assert tuple(re.findall(r'"([A-Z]{6})"', block.group(1))) == universe.symbols


def test_line_endings_do_not_change_the_universe_hash() -> None:
    loaded, universe = load_real()
    crlf = ("\r\n".join(_map_lines()) + "\r\n").encode()
    assert load_symbol_universe_bytes(crlf, loaded).canonical_sha256 == universe.canonical_sha256


def test_twenty_nine_symbol_map_is_rejected() -> None:
    loaded, _ = load_real()
    raw = ("\n".join(_map_lines()[:-1]) + "\n").encode()
    with pytest.raises(HarnessInputError) as info:
        load_symbol_universe_bytes(raw, loaded)
    assert info.value.code == "SYMBOL_COUNT_MISMATCH"


def test_duplicate_canonical_pair_in_map_is_rejected() -> None:
    loaded, _ = load_real()
    lines = _map_lines()
    lines[2] = "EURUSD,GBPUSD"
    with pytest.raises(HarnessInputError) as info:
        load_symbol_universe_bytes(("\n".join(lines) + "\n").encode(), loaded)
    assert info.value.code == "CANONICAL_SYMBOL_DUPLICATE"


def test_edited_map_breaks_the_policy_pin() -> None:
    loaded, _ = load_real()
    lines = _map_lines()
    lines[1], lines[2] = lines[2], lines[1]
    with pytest.raises(HarnessInputError) as info:
        load_symbol_universe_bytes(("\n".join(lines) + "\n").encode(), loaded)
    assert info.value.code == "SYMBOL_MAP_SHA_MISMATCH"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ({"expected_symbol_count": 29}, "POLICY_SCHEMA_INVALID"),
        ({"required_broker_submit_count": 1}, "POLICY_SCHEMA_INVALID"),
        ({"operator_pair_selection_allowed": True}, "POLICY_SCHEMA_INVALID"),
        ({"unexpected_threshold": 3}, "POLICY_SCHEMA_INVALID"),
        ({"contamination_rule": "EXACT_PRICE_VECTOR"}, "POLICY_SCHEMA_INVALID"),
        ({"price_vector_overlap": "FAIL"}, "POLICY_SCHEMA_INVALID"),
        ({"exact_s_acceptance_rule": "ANY"}, "POLICY_SCHEMA_INVALID"),
        ({"exact_s_acceptance_rule": "R9_ARTIFACT_BOUND"}, "POLICY_SCHEMA_INVALID"),
        ({"exact_s_identity_binding": "EXACT_S_ID_ONLY"}, "POLICY_SCHEMA_INVALID"),
        ({"bundle_schema": "wolf15.shadow-harness.bundle.v1"}, "POLICY_SCHEMA_INVALID"),
        ({"r9_envelope_status": "NOT_FROZEN"}, "POLICY_SCHEMA_INVALID"),
        ({"r9_binding": "ANY"}, "POLICY_SCHEMA_INVALID"),
        ({"r9_binding": "R9_ARTIFACT_SHA256_MATCH_ONLY"}, "POLICY_SCHEMA_INVALID"),
        ({"r9_envelope_schema_relpath": "docs/governance/other.md"}, "POLICY_SCHEMA_INVALID"),
        ({"r9_envelope_frozen_schema_sha256": "0" * 64}, "POLICY_SCHEMA_INVALID"),
        (
            {"r9_envelope_frozen_schema_sha256": "2a5826a36f1ed9f0a099f1fd03aad52629141e76fdb9d5c7978aa2626f660f82"},
            "POLICY_SCHEMA_INVALID",
        ),
        ({"r9_envelope_frozen_normative_span_sha256": "0" * 64}, "POLICY_SCHEMA_INVALID"),
        ({"shadow_acceptance_rule": "GATE_PASSED_ONLY"}, "POLICY_SCHEMA_INVALID"),
        ({"evidence_scope_rule": "DEFAULT_GLOBAL"}, "POLICY_SCHEMA_INVALID"),
        ({"pair_scoped_evidence_reuse": "DIAGNOSTIC_ONLY"}, "POLICY_SCHEMA_INVALID"),
        ({"global_scoped_evidence_reuse": "IGNORED"}, "POLICY_SCHEMA_INVALID"),
        ({"pair_scope_binding_rule": "SYMBOL_ONLY"}, "POLICY_SCHEMA_INVALID"),
        ({"pair_binding_required_capture_kinds": ["CANDIDATE"]}, "POLICY_SCHEMA_INVALID"),
        ({"global_scope_allowed_capture_kinds": ["CANDIDATE"]}, "POLICY_SCHEMA_INVALID"),
        ({"global_scope_allowed_capture_kinds": ["TRADEPLAN"]}, "POLICY_SCHEMA_INVALID"),
        ({"global_scope_allowed_capture_kinds": ["RISK_DRY_RUN"]}, "POLICY_SCHEMA_INVALID"),
        ({"global_scope_forbidden_capture_kinds": ["CANDIDATE", "TRADEPLAN"]}, "POLICY_SCHEMA_INVALID"),
        ({"global_scope_violation": "DIAGNOSTIC_ONLY"}, "POLICY_SCHEMA_INVALID"),
    ],
)
def test_policy_rejects_changed_or_hidden_values(mutation: dict[str, Any], code: str) -> None:
    payload = _policy_payload() | mutation
    with pytest.raises(HarnessInputError) as info:
        load_policy_bytes(json.dumps(payload).encode())
    assert info.value.code == code


def test_policy_1_4_0_pins_scope_and_final_acceptance_rules() -> None:
    loaded, _ = load_real()
    policy = loaded.policy
    assert policy.policy_version == "1.4.0"
    assert (policy.evidence_scope_rule, policy.pair_scoped_evidence_reuse, policy.global_scoped_evidence_reuse) == (
        "EXPLICIT_REQUIRED",
        "CROSS_PAIR_CONTAMINATION",
        "DIAGNOSTIC_ONLY",
    )
    assert policy.pair_scope_binding_rule == "EXACT_CANONICAL_SYMBOL_AND_LIFECYCLE_AND_REVISION"
    assert tuple(policy.pair_binding_required_capture_kinds) == PAIR_BINDING_REQUIRED_CAPTURE_KINDS
    assert tuple(policy.global_scope_allowed_capture_kinds) == GLOBAL_SCOPE_ALLOWED_CAPTURE_KINDS == ()
    assert tuple(policy.global_scope_forbidden_capture_kinds) == GLOBAL_SCOPE_FORBIDDEN_CAPTURE_KINDS == CAPTURE_KINDS
    assert policy.global_scope_violation == "REJECT_BUNDLE"
    assert (policy.r9_binding, policy.r9_envelope_status, policy.shadow_acceptance_rule) == (
        "R9_ENVELOPE_V1_VERIFIER_VERDICT_ONLY",
        "FROZEN",
        "GATE_PASSED_AND_EXACT_S_ACCEPTED_AND_R9_ENVELOPE_FROZEN",
    )
    assert (policy.exact_s_acceptance_rule, policy.exact_s_identity_binding) == (
        "R9_ENVELOPE_V1_VERIFIED_AND_SNAPSHOT_S_BOUND",
        "EXACT_S_ID_EQ_SNAPSHOT_S_ID_AND_EXACT_S_SHA256_EQ_SNAPSHOT_S_SHA256",
    )
    assert (policy.r9_envelope_schema_relpath, policy.r9_envelope_frozen_schema_sha256) == (
        "docs/governance/r9-envelope-v1.md",
        "10732eebab7e8a3a9270be6d378689e6160bd7a8087520ee2d86bf156e7588a2",
    )


@pytest.mark.parametrize(
    "field",
    [
        "evidence_scope_rule",
        "pair_scoped_evidence_reuse",
        "global_scoped_evidence_reuse",
        "r9_binding",
        "r9_envelope_status",
        "r9_envelope_schema_relpath",
        "r9_envelope_frozen_schema_sha256",
        "r9_envelope_frozen_normative_span_sha256",
        "exact_s_acceptance_rule",
        "exact_s_identity_binding",
        "shadow_acceptance_rule",
        "pair_scope_binding_rule",
        "pair_binding_required_capture_kinds",
        "global_scope_allowed_capture_kinds",
        "global_scope_forbidden_capture_kinds",
        "global_scope_violation",
    ],
)
def test_policy_1_3_0_and_1_4_0_fields_are_required_not_defaulted(field: str) -> None:
    payload = _policy_payload()
    del payload[field]
    with pytest.raises(HarnessInputError) as info:
        load_policy_bytes(json.dumps(payload).encode())
    assert info.value.code == "POLICY_SCHEMA_INVALID"


def test_policy_missing_value_is_rejected_not_defaulted() -> None:
    payload = _policy_payload()
    del payload["no_candidate_status"]
    with pytest.raises(HarnessInputError) as info:
        load_policy_bytes(json.dumps(payload).encode())
    assert info.value.code == "POLICY_SCHEMA_INVALID"


def test_policy_duplicate_json_key_is_rejected() -> None:
    raw = POLICY_PATH.read_bytes().replace(b'"policy_version"', b'"policy_version": "9.9.9",\n  "policy_version"', 1)
    with pytest.raises(HarnessInputError) as info:
        load_policy_bytes(raw)
    assert info.value.code == "DUPLICATE_JSON_KEY"


def test_policy_hash_is_content_bound_and_format_independent() -> None:
    loaded, _ = load_real()
    reformatted = json.dumps(_policy_payload(), indent=None).encode()
    assert load_policy_bytes(reformatted).policy_sha256 == loaded.policy_sha256
    bumped = json.dumps(_policy_payload() | {"policy_version": "1.0.1"}).encode()
    assert load_policy_bytes(bumped).policy_sha256 != loaded.policy_sha256


def test_policy_symbol_map_path_must_be_repository_relative() -> None:
    payload = _policy_payload() | {"symbol_map_relpath": "../outside.csv"}
    loaded = load_policy_bytes(json.dumps(payload).encode())
    with pytest.raises(HarnessInputError) as info:
        resolve_symbol_map_path(loaded, REPO_ROOT)
    assert info.value.code == "SYMBOL_MAP_PATH_INVALID"


def test_capture_models_are_frozen_and_forbid_extra_fields() -> None:
    record = CandidateCapture.model_validate(candidate("EURUSD"))
    with pytest.raises(ValidationError):
        record.direction = "SELL"
    with pytest.raises(ValidationError):
        CandidateCapture.model_validate(candidate("EURUSD") | {"lot_size": "1.0"})


def test_capture_requires_utc_timestamp_and_kind_lineage() -> None:
    with pytest.raises(ValidationError, match="UTC offset"):
        CandidateCapture.model_validate(candidate("EURUSD", captured_at_utc="2026-09-22T08:00:00"))
    broken = tradeplan("EURUSD")
    broken["lineage"] = broken["lineage"] | {"target_id": None}
    with pytest.raises(ValidationError, match="target_id"):
        TradeplanCapture.model_validate(broken)


def test_prices_reject_binary_floats_and_duplicates() -> None:
    with pytest.raises(ValidationError, match="binary floats"):
        PricePoint(name="ENTRY", value=1.1)  # type: ignore[arg-type]
    duplicated = tradeplan("EURUSD")
    duplicated["prices"] = [duplicated["prices"][0], duplicated["prices"][0]]
    with pytest.raises(ValidationError, match="unique"):
        TradeplanCapture.model_validate(duplicated)


def test_dry_run_captures_must_be_dry_run() -> None:
    _, universe = load_real()
    broker = broker_dry_run("EURUSD", universe)
    risk = risk_dry_run("EURUSD")
    assert BrokerAdaptationDryRunCapture.model_validate(broker).dry_run is True
    assert RiskDryRunCapture.model_validate(risk).dry_run is True
    with pytest.raises(ValidationError):
        BrokerAdaptationDryRunCapture.model_validate(broker | {"dry_run": False})
    with pytest.raises(ValidationError):
        RiskDryRunCapture.model_validate(risk | {"dry_run": False})
