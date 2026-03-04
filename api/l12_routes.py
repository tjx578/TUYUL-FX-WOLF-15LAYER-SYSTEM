from __future__ import annotations

import contextlib
from typing import Any, Protocol, cast

from fastapi import Depends, HTTPException
from fastapi.routing import APIRouter

from api.middleware.auth import verify_token
from config_loader import load_pairs
from context.live_context_bus import LiveContextBus
from execution.state_machine import ExecutionStateMachine
from storage.l12_cache import get_verdict
from utils.timezone_utils import format_local, format_utc, now_utc

router: APIRouter = APIRouter()


class _SnapshotProvider(Protocol):
    def snapshot(self) -> dict[str, Any]:
        ...


def _load_available_pairs() -> list[dict[str, str | bool]]:
    """Load pair metadata from config/pairs.yaml for API endpoints."""
    available: list[dict[str, str | bool]] = []
    for pair in load_pairs():
        symbol = str(pair.get("symbol", "")).upper().strip()
        if not symbol:
            continue
        available.append({
            "symbol": symbol,
            "name": str(pair.get("name") or symbol),
            "enabled": bool(pair.get("enabled", True)),
        })
    return available


AVAILABLE_PAIRS: list[dict[str, str | bool]] = _load_available_pairs()


@router.get("/api/v1/l12/{pair}", dependencies=[Depends(verify_token)])
def fetch_l12(pair: str):
    """Get L12 verdict for a specific pair with timezone info."""
    data = get_verdict(pair.upper())
    if not data:
        raise HTTPException(status_code=404, detail=f"No verdict found for {pair}")

    # Add dual timezone info if timestamp exists
    if "timestamp" in data:
        with contextlib.suppress(Exception):
            current_time = now_utc()
            data["time_utc"] = format_utc(current_time)
            data["time_local"] = format_local(current_time)

    return data


@router.get("/api/v1/verdict/all", dependencies=[Depends(verify_token)])
def fetch_all_verdicts() -> dict[str, Any]:
    """Get verdicts for all available pairs."""
    verdicts: dict[str, Any] = {}
    for pair_info in AVAILABLE_PAIRS:
        pair = pair_info["symbol"]
        if not isinstance(pair, str):
            continue
        data = get_verdict(pair)
        if data:
            verdicts[pair] = data

    return verdicts


@router.get("/api/v1/verdict", dependencies=[Depends(verify_token)])
def fetch_all_verdicts_alias() -> dict[str, Any]:
    """Compatibility alias: return verdicts for all available pairs."""
    return fetch_all_verdicts()


@router.get("/api/v1/context", dependencies=[Depends(verify_token)])
def fetch_context() -> dict[str, Any]:
    """Get live context snapshot."""
    context_bus = LiveContextBus()
    snapshot: dict[str, Any] = cast(dict[str, Any], context_bus.snapshot())

    # Add timestamp info
    current_time = now_utc()
    snapshot["timestamp_utc"] = format_utc(current_time)
    snapshot["timestamp_local"] = format_local(current_time)

    return snapshot


@router.get("/api/v1/execution", dependencies=[Depends(verify_token)])
def fetch_execution() -> dict[str, Any]:
    """Get current execution state."""
    state_machine = cast(_SnapshotProvider, ExecutionStateMachine())
    execution_state = state_machine.snapshot()

    # Add timezone info
    current_time = now_utc()
    execution_state["current_time_utc"] = format_utc(current_time)
    execution_state["current_time_local"] = format_local(current_time)

    return execution_state


@router.get("/api/v1/pairs")
def fetch_pairs():
    """Get list of available currency pairs."""
    return AVAILABLE_PAIRS


# ---------------------------------------------------------------------------
# Pipeline endpoint — maps L12 verdict to PipelineData for dashboard UI
# ---------------------------------------------------------------------------

# Gate name → display label mapping
_GATE_LABELS: dict[str, str] = {
    "gate_1_tii": "TII Sym",
    "gate_2_integrity": "Integrity",
    "gate_3_rr": "R:R",
    "gate_4_fta": "FTA",
    "gate_5_montecarlo": "MC WR",
    "gate_6_propfirm": "PropFirm",
    "gate_7_drawdown": "DD",
    "gate_8_latency": "Latency",
    "gate_9_conf12": "Conf",
}

# Canonical 15-layer definitions
_LAYER_DEFS: list[dict[str, str]] = [
    {"id": "L1",  "name": "Context",     "zone": "COG"},
    {"id": "L2",  "name": "MTA",         "zone": "COG"},
    {"id": "L3",  "name": "Technical",   "zone": "ANA"},
    {"id": "L4",  "name": "Scoring",     "zone": "ANA"},
    {"id": "L5",  "name": "Psychology",  "zone": "META"},
    {"id": "L6",  "name": "Risk",        "zone": "META"},
    {"id": "L7",  "name": "Monte Carlo", "zone": "ANA"},
    {"id": "L8",  "name": "TII",         "zone": "ANA"},
    {"id": "L9",  "name": "SMC/VP",      "zone": "ANA"},
    {"id": "L10", "name": "Position",    "zone": "EXEC"},
    {"id": "L11", "name": "Execution",   "zone": "EXEC"},
    {"id": "L12", "name": "Verdict",     "zone": "VER"},
    {"id": "L13", "name": "Reflect",     "zone": "POST"},
    {"id": "L14", "name": "Export",      "zone": "POST"},
    {"id": "L15", "name": "Sovereign",   "zone": "POST"},
]


def _build_pipeline_data(pair: str, verdict_data: dict[str, Any]) -> dict[str, Any]:
    """Transform L12 verdict cache data into PipelineData shape for the UI."""

    gates_raw: dict[str, Any] = verdict_data.get("gates", {})
    scores: dict[str, Any] = verdict_data.get("scores", {})
    execution: dict[str, Any] = verdict_data.get("execution", {})
    layers_raw: dict[str, Any] = verdict_data.get("layers", {})

    verdict_str: str = verdict_data.get("verdict", "UNKNOWN")
    confidence = verdict_data.get("confidence", 0)
    # Confidence may be a string label or numeric — normalise to 0–1 float
    if isinstance(confidence, str):
        conf_map = {"LOW": 0.25, "MEDIUM": 0.50, "HIGH": 0.75, "VERY_HIGH": 0.95}
        confidence_num = conf_map.get(confidence.upper(), 0.5)
    else:
        confidence_num = float(confidence)

    wolf_status: str = verdict_data.get("wolf_status", "—")
    latency: int = int(verdict_data.get("system", {}).get("latency_ms", 0)
                       or gates_raw.get("gate_8_latency_val", 0))

    # ── Build gate array ──────────────────────────────────────────────────
    gate_list: list[dict[str, Any]] = []
    for key, label in _GATE_LABELS.items():
        gate_val = gates_raw.get(key)
        passed = gate_val == "PASS" if isinstance(gate_val, str) else bool(gate_val)
        gate_list.append({
            "name": label,
            "val": gate_val if gate_val is not None else "—",
            "thr": "—",
            "pass": passed,
        })

    # ── Build layer array with available scores ───────────────────────────
    # Map known score keys to layer IDs
    layer_score_map: dict[str, tuple[str, str]] = {
        "L7":  (str(layers_raw.get("L7_monte_carlo_win", "—")), "MC"),
        "L8":  (str(scores.get("tii", layers_raw.get("L8_tii_sym", "—"))), "integ"),
        "L12": (
            f"{gates_raw.get('passed', '?')}/{gates_raw.get('total', '?')}",
            verdict_str.split("_")[0] if "_" in verdict_str else verdict_str,
        ),
    }

    pass_count = int(gates_raw.get("passed", 0))
    total_gates = int(gates_raw.get("total", 9))

    layer_list: list[dict[str, str]] = []
    for ldef in _LAYER_DEFS:
        lid = ldef["id"]
        val, detail = layer_score_map.get(lid, ("—", "—"))
        # Determine status from gate results or default
        if lid == "L12":
            status = "pass" if pass_count == total_gates else ("warn" if pass_count >= 7 else "fail")
        else:
            status = "pass"  # default — layers don't have individual pass/fail in cache
        layer_list.append({
            "id": lid,
            "name": ldef["name"],
            "zone": ldef["zone"],
            "status": status,
            "val": val,
            "detail": detail,
        })

    # ── Entry data (from execution block if present) ──────────────────────
    entry: dict[str, Any] = {
        "price": execution.get("entry_price", 0),
        "sl": execution.get("stop_loss", 0),
        "tp1": execution.get("take_profit_1", 0),
        "tp2": execution.get("take_profit_2"),
        "rr": str(execution.get("rr_ratio", "—")),
        "lots": execution.get("lot_size", 0),
        "risk$": execution.get("risk_amount", 0),
        "reward$": execution.get("reward_amount", 0),
    }

    execution_map_raw = verdict_data.get("execution_map")
    if isinstance(execution_map_raw, dict):
        execution_map = execution_map_raw
    else:
        execution_map = {
            "pair": pair,
            "timestamp": verdict_data.get("timestamp", ""),
            "layers_executed": [layer["id"] for layer in layer_list],
            "engines_invoked": [],
            "halt_reason": None,
            "constitutional_verdict": verdict_str,
        }

    return {
        "pair": pair,
        "verdict": verdict_str,
        "wolfGrade": wolf_status,
        "confidence": round(confidence_num, 4),
        "latency": latency,
        "layers": layer_list,
        "gates": gate_list,
        "entry": entry,
        "execution_map": execution_map,
    }


@router.get("/api/v1/pipeline/{pair}", dependencies=[Depends(verify_token)])
def fetch_pipeline(pair: str):
    """Get full pipeline data for the PipelinePanel UI component.

    Transforms the cached L12 verdict into the PipelineData shape
    consumed by the Next.js dashboard.
    """
    raw = get_verdict(pair.upper())
    if not raw:
        raise HTTPException(status_code=404, detail=f"No pipeline data for {pair}")
    return _build_pipeline_data(pair.upper(), raw)
