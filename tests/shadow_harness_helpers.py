"""Deterministic builders for the offline shadow-harness tests (no runtime imports)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tools.shadow_harness.evaluator import ShadowHarnessReport, evaluate_bundle_bytes
from tools.shadow_harness.manifest import (
    LoadedPolicy,
    SymbolUniverse,
    load_policy,
    load_symbol_universe,
    resolve_symbol_map_path,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "tools" / "shadow_harness" / "policy" / "shadow_harness_policy_v1.json"
CAPTURE_SCHEMA = "wolf15.shadow-harness.capture.v1"
CAPTURED_AT = "2026-09-22T08:00:00+00:00"


def load_real() -> tuple[LoadedPolicy, SymbolUniverse]:
    loaded = load_policy(POLICY_PATH)
    return loaded, load_symbol_universe(resolve_symbol_map_path(loaded, REPO_ROOT), loaded)


def digest(*parts: object) -> str:
    return hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest()


def lineage(symbol: str, n: int) -> dict[str, str]:
    return {
        "lifecycle_id": f"5scr-lifecycle:{digest('lc', symbol, n)[:32]}",
        "thesis_id": f"5scr-thesis:{digest('th', symbol, n)[:32]}",
        "box_id": f"5scr-execution-box:{digest('bx', symbol, n)[:32]}",
        "target_id": f"target-{digest('tg', symbol, n)[:32]}",
        "tradeplan_id": f"5scr-tradeplan-v2:{digest('tp', symbol, n)[:32]}",
    }


def _base(symbol: str, n: int, kind: str, lineage_ids: dict[str, str | None]) -> dict[str, Any]:
    return {
        "capture_schema_version": CAPTURE_SCHEMA,
        "capture_kind": kind,
        "capture_id": f"cap-{kind.lower()}-{symbol}-{n}",
        "symbol": symbol,
        "captured_at_utc": CAPTURED_AT,
        "evidence_sha256": digest("evidence", kind, symbol, n),
        "lineage": {
            "lifecycle_id": None,
            "thesis_id": None,
            "box_id": None,
            "target_id": None,
            "tradeplan_id": None,
        }
        | lineage_ids,
    }


def candidate(symbol: str, n: int = 1, **overrides: Any) -> dict[str, Any]:
    ids = lineage(symbol, n)
    record = _base(symbol, n, "CANDIDATE", {"lifecycle_id": ids["lifecycle_id"], "thesis_id": ids["thesis_id"]})
    record |= {
        "candidate_id": f"cand-{symbol}-{n}",
        "direction": "BUY",
        "pair_selection_source": "STRATEGY",
        "direction_selection_source": "STRATEGY",
    }
    return record | overrides


def exact_s(symbol: str, n: int = 1, **overrides: Any) -> dict[str, Any]:
    ids = lineage(symbol, n)
    record = _base(
        symbol,
        n,
        "EXACT_S",
        {"lifecycle_id": ids["lifecycle_id"], "thesis_id": ids["thesis_id"], "box_id": ids["box_id"]},
    )
    record |= {"exact_s_id": f"exact-s-{symbol}-{n}", "exact_s_sha256": digest("exact-s", symbol, n)}
    return record | overrides


def prices(seed: int) -> list[dict[str, str]]:
    return [
        {"name": "ENTRY", "value": f"1.{10000 + seed}"},
        {"name": "STOP_LOSS", "value": f"1.{9000 + seed}"},
        {"name": "TAKE_PROFIT", "value": f"1.{12000 + seed}"},
    ]


def tradeplan(symbol: str, n: int = 1, seed: int | None = None, **overrides: Any) -> dict[str, Any]:
    record = _base(symbol, n, "TRADEPLAN", dict(lineage(symbol, n)))
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
    record = _base(symbol, n, "BROKER_ADAPTATION_DRY_RUN", {"tradeplan_id": lineage(symbol, n)["tradeplan_id"]})
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
    record = _base(symbol, n, "RISK_DRY_RUN", {"tradeplan_id": lineage(symbol, n)["tradeplan_id"]})
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
        "run_id": "shadow-run-001",
        "symbol_universe": universe.universe_id,
        "symbol_universe_sha256": universe.canonical_sha256,
        "policy_version": loaded.policy.policy_version,
        "policy_sha256": loaded.policy_sha256,
        "capture_schema_version": CAPTURE_SCHEMA,
        "operator_selected_symbols": [],
        "operator_direction_overrides": [],
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
        "bundle_schema": "wolf15.shadow-harness.bundle.v1",
        "header": header(loaded, universe, **(header_overrides or {})),
        "captures_by_symbol": by_symbol,
    }


def encode(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def evaluate(payload: dict[str, Any], loaded: LoadedPolicy, universe: SymbolUniverse) -> ShadowHarnessReport:
    return evaluate_bundle_bytes(encode(payload), loaded, universe)
