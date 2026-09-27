"""Deterministic builders for the offline shadow-harness tests (no runtime imports)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tools.shadow_harness.evaluator import ShadowHarnessReport, evaluate_bundle_bytes
from tools.shadow_harness.manifest import (
    LoadedPolicy,
    R9EnvelopePin,
    SymbolUniverse,
    load_policy,
    load_r9_envelope_pin,
    load_symbol_universe,
    resolve_symbol_map_path,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "tools" / "shadow_harness" / "policy" / "shadow_harness_policy_v1.json"
R9_SCHEMA_DOC = REPO_ROOT / "docs" / "governance" / "r9-envelope-v1.md"
CAPTURE_SCHEMA = "wolf15.shadow-harness.capture.v1"
BUNDLE_SCHEMA = "shadow_capture_bundle/v1"
CAPTURED_AT = "2026-09-22T08:00:00+00:00"

# Fixture R9 evidence: artifact bytes, the exact snapshot S they attest, and the one evidence id of the chain.
R9_ARTIFACT_BYTES = b'{"run_id":"SHADOW_HARNESS_FIXTURE_R9","status":"PASS_CLOSED"}\n'
R9_ARTIFACT_SHA256 = hashlib.sha256(R9_ARTIFACT_BYTES).hexdigest()
S_ID = "snap-shadow-fixture-0001"
S_SHA256 = hashlib.sha256(b"fixture snapshot S").hexdigest()
R9_EVIDENCE_ID = "4a46f1fd-54e3-4241-9c03-8e0fa385a02d"


def load_real() -> tuple[LoadedPolicy, SymbolUniverse]:
    loaded = load_policy(POLICY_PATH)
    return loaded, load_symbol_universe(resolve_symbol_map_path(loaded, REPO_ROOT), loaded)


def load_pin(loaded: LoadedPolicy) -> R9EnvelopePin:
    return load_r9_envelope_pin(loaded, REPO_ROOT)


def digest(*parts: object) -> str:
    return hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest()


def r9_envelope(artifact: bytes = R9_ARTIFACT_BYTES, **overrides: Any) -> dict[str, Any]:
    """A valid ``R9EnvelopeV1`` wire object over ``artifact`` for snapshot S (direct receipt ABSENT)."""

    s = {"snapshot_id": S_ID, "snapshot_sha256": S_SHA256}
    payload_sha256 = digest("r9-import-payload")
    envelope: dict[str, Any] = {
        "schema_id": "wolf15.r9-envelope",
        "schema_version": "v1",
        "source_artifact": "R9",
        "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
        "snapshot_s": dict(s),
        "collect": {
            "status": "MATCHED_FLAT_DEMO",
            "attested_snapshot_identity": dict(s),
            "evidence_id": R9_EVIDENCE_ID,
            "report_sha256": digest("r9-collect-report"),
        },
        "import": {
            "status": "STORED",
            "imported_snapshot_identity": dict(s),
            "evidence_id": R9_EVIDENCE_ID,
            "payload_sha256": payload_sha256,
        },
        "active_readback": {
            "status": "ACTIVE",
            "readback_snapshot_identity": dict(s),
            "evidence_id": R9_EVIDENCE_ID,
            "payload_sha256": payload_sha256,
        },
        "capability": {
            "status": "MEASURED",
            "snapshot_id": S_ID,
            "canonical_symbol": "EURUSD",
            "broker_symbol": "EURUSD",
            "volume_min": 0.01,
            "volume_step": 0.01,
        },
        "direct_receipt": {
            "status": "ABSENT",
            "snapshot_id": S_ID,
            "reconciliation_id": None,
            "receipt_sha256": None,
            "broker_ledger_reconciled": None,
        },
        "created_at": "2026-09-28T00:00:00Z",
    }
    return envelope | overrides


def lineage(symbol: str, n: int) -> dict[str, str]:
    return {
        "lifecycle_id": f"5scr-lifecycle:{digest('lc', symbol, n)[:32]}",
        "thesis_id": f"5scr-thesis:{digest('th', symbol, n)[:32]}",
        "proof_id": f"5scr-proof:{digest('pf', symbol, n)[:32]}",
        "pressure_range_id": f"5scr-pressure-range:{digest('pr', symbol, n)[:32]}",
        "target_id": f"target-{digest('tg', symbol, n)[:32]}",
        "execution_box_id": f"5scr-execution-box:{digest('bx', symbol, n)[:32]}",
        "tradeplan_candidate_id": f"5scr-tradeplan-v2:{digest('tp', symbol, n)[:32]}",
    }


def _empty_lineage() -> dict[str, str | None]:
    return {
        "lifecycle_id": None,
        "thesis_id": None,
        "proof_id": None,
        "pressure_range_id": None,
        "target_id": None,
        "execution_box_id": None,
        "tradeplan_candidate_id": None,
    }


def _base(symbol: str, n: int, kind: str, lineage_ids: dict[str, str]) -> dict[str, Any]:
    return {
        "capture_schema_version": CAPTURE_SCHEMA,
        "capture_kind": kind,
        "capture_id": f"cap-{kind.lower()}-{symbol}-{n}",
        "symbol": symbol,
        "captured_at_utc": CAPTURED_AT,
        "evidence_sha256": digest("evidence", kind, symbol, n),
        "evidence_scope": "PAIR",
        "lineage": _empty_lineage() | lineage_ids,
    }


def _pick(symbol: str, n: int, *names: str) -> dict[str, str]:
    ids = lineage(symbol, n)
    return {name: ids[name] for name in names}


def candidate(symbol: str, n: int = 1, **overrides: Any) -> dict[str, Any]:
    record = _base(symbol, n, "CANDIDATE", _pick(symbol, n, "lifecycle_id", "thesis_id"))
    record |= {
        "candidate_id": f"cand-{symbol}-{n}",
        "candidate_revision": 1,
        "direction": "BUY",
        "pair_selection_source": "STRATEGY",
        "direction_selection_source": "STRATEGY",
    }
    return record | overrides


def exact_s(symbol: str, n: int = 1, **overrides: Any) -> dict[str, Any]:
    """Pre-R9 exact-S capture: NOT_MEASURED, no id/digest (the harness never fabricates one)."""

    record = _base(
        symbol,
        n,
        "EXACT_S",
        _pick(symbol, n, "lifecycle_id", "thesis_id", "proof_id", "execution_box_id"),
    )
    record |= {
        "exact_s_status": "NOT_MEASURED",
        "exact_s_id": None,
        "exact_s_sha256": None,
        "r9_artifact_sha256": None,
    }
    return record | overrides


def measured_exact_s(symbol: str, r9_artifact_sha256: str, n: int = 1, **overrides: Any) -> dict[str, Any]:
    measured = {
        "exact_s_status": "MEASURED",
        "exact_s_id": f"exact-s-{symbol}-{n}",
        "exact_s_sha256": digest("exact-s", symbol, n),
        "r9_artifact_sha256": r9_artifact_sha256,
    }
    return exact_s(symbol, n) | measured | overrides


def bound_exact_s(symbol: str, n: int = 1, **overrides: Any) -> dict[str, Any]:
    """MEASURED exact-S bound to the fixture envelope: exact_s_id/sha256 = snapshot_s, r9 digest = artifact."""

    bound = {"exact_s_id": S_ID, "exact_s_sha256": S_SHA256}
    return measured_exact_s(symbol, R9_ARTIFACT_SHA256, n) | bound | overrides


def prices(seed: int) -> list[dict[str, str]]:
    return [
        {"name": "ENTRY", "value": f"1.{10000 + seed}"},
        {"name": "STOP_LOSS", "value": f"1.{9000 + seed}"},
        {"name": "TAKE_PROFIT", "value": f"1.{12000 + seed}"},
    ]


def tradeplan(symbol: str, n: int = 1, seed: int | None = None, **overrides: Any) -> dict[str, Any]:
    record = _base(
        symbol,
        n,
        "TRADEPLAN",
        _pick(
            symbol,
            n,
            "lifecycle_id",
            "thesis_id",
            "pressure_range_id",
            "target_id",
            "execution_box_id",
            "tradeplan_candidate_id",
        ),
    )
    record |= {
        "tradeplan_revision": 1,
        "direction": "BUY",
        "direction_selection_source": "STRATEGY",
        "prices": prices(seed if seed is not None else int(digest(symbol, n)[:3], 16)),
    }
    return record | overrides


def broker_dry_run(
    symbol: str, universe: SymbolUniverse, n: int = 1, seed: int | None = None, **overrides: Any
) -> dict[str, Any]:
    record = _base(symbol, n, "BROKER_ADAPTATION_DRY_RUN", _pick(symbol, n, "tradeplan_candidate_id"))
    record |= {
        "dry_run": True,
        "adaptation_id": f"adapt-{symbol}-{n}",
        "broker_symbol": universe.broker_symbol_for(symbol),
        "adaptation_status": "ADAPTED",
        "broker_submit_attempted": False,
        "prices": prices(seed if seed is not None else int(digest(symbol, n)[:3], 16)),
    }
    return record | overrides


def risk_dry_run(symbol: str, n: int = 1, **overrides: Any) -> dict[str, Any]:
    record = _base(symbol, n, "RISK_DRY_RUN", _pick(symbol, n, "tradeplan_candidate_id"))
    record |= {
        "dry_run": True,
        "risk_evaluation_id": f"risk-{symbol}-{n}",
        "risk_decision": "ALLOW",
        "broker_submit_attempted": False,
    }
    return record | overrides


def natural_chain(symbol: str, universe: SymbolUniverse, n: int = 1) -> list[dict[str, Any]]:
    return [
        candidate(symbol, n),
        exact_s(symbol, n),
        tradeplan(symbol, n),
        broker_dry_run(symbol, universe, n),
        risk_dry_run(symbol, n),
    ]


def header(loaded: LoadedPolicy, universe: SymbolUniverse, **overrides: Any) -> dict[str, Any]:
    return {
        "schema_version": BUNDLE_SCHEMA,
        "candidate_git_sha": digest("git")[:40],
        "candidate_tree_digest": digest("tree")[:40],
        "manifest_hash": universe.canonical_sha256,
        "SSOT_hash": digest("ssot"),
        "A1_hash": digest("a1"),
        "A2_hash": digest("a2"),
        "A3_hash": digest("a3"),
        "A4_hash": None,
        "configuration_digest": loaded.policy_sha256,
        "created_at": CAPTURED_AT,
    } | overrides


def bundle(
    loaded: LoadedPolicy,
    universe: SymbolUniverse,
    captures: dict[str, list[dict[str, Any]]] | None = None,
    *,
    symbols: tuple[str, ...] | None = None,
    header_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    keys = universe.symbols if symbols is None else symbols
    by_symbol: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in keys}
    by_symbol.update(captures or {})
    return {
        "header": header(loaded, universe, **(header_overrides or {})),
        "captures_by_symbol": by_symbol,
    }


def encode(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def evaluate(
    payload: dict[str, Any],
    loaded: LoadedPolicy,
    universe: SymbolUniverse,
    *,
    r9_envelope: dict[str, Any] | bytes | None = None,
    r9_artifact: bytes | None = None,
) -> ShadowHarnessReport:
    """Evaluate with the pin verified from the real schema document; R9 inputs default to not supplied."""

    envelope = encode(r9_envelope) if isinstance(r9_envelope, dict) else r9_envelope
    return evaluate_bundle_bytes(
        encode(payload),
        loaded,
        universe,
        r9_envelope_pin=load_pin(loaded),
        r9_envelope=envelope,
        r9_artifact=r9_artifact,
    )
