from __future__ import annotations

import contextlib
import time
from typing import Any, Protocol, cast

from fastapi import Depends, HTTPException
from fastapi.routing import APIRouter

from config_loader import load_pairs
from execution.state_machine import ExecutionStateMachine
from storage.l12_cache import KEY_PREFIX, VERDICT_TTL_SEC, get_verdict, is_verdict_stale
from utils.timezone_utils import format_local, format_utc, now_utc

from .middleware.auth import verify_token
from .redis_context_reader import RedisContextReader

router: APIRouter = APIRouter()


class _SnapshotProvider(Protocol):
    def snapshot(self) -> dict[str, Any]: ...


def _load_available_pairs() -> list[dict[str, str | bool]]:
    """Load pair metadata from config/pairs.yaml for API endpoints."""
    available: list[dict[str, str | bool]] = []
    for pair in load_pairs():
        symbol = str(pair.get("symbol", "")).upper().strip()
        if not symbol:
            continue
        available.append(
            {
                "symbol": symbol,
                "name": str(pair.get("name") or symbol),
                "enabled": bool(pair.get("enabled", True)),
            }
        )
    return available


AVAILABLE_PAIRS: list[dict[str, str | bool]] = _load_available_pairs()
_WARMUP_MIN_BARS: dict[str, int] = {
    "H1": 20,
    "H4": 10,
    "D1": 5,
    "W1": 4,
    "MN": 2,
}


def _build_meta(data: dict[str, Any]) -> dict[str, Any]:
    """Build _meta block with cache age for staleness detection."""
    cached_at = data.get("_cached_at")
    age = round(time.time() - float(cached_at), 3) if cached_at is not None else None
    return {
        "age_seconds": age,
        "cached_at": cached_at,
        "cache_ttl_seconds": VERDICT_TTL_SEC,
    }


def _extract_hold_block_reason(raw: dict[str, Any] | None) -> str | None:
    if not raw:
        return None
    reason = raw.get("last_hold_block_reason")
    if isinstance(reason, str) and reason:
        return reason
    errors = raw.get("errors")
    if isinstance(errors, list):
        for err in errors:
            if isinstance(err, str) and (
                err.startswith("GOVERNANCE_BLOCK:")
                or err.startswith("GOVERNANCE_HOLD:")
                or err.startswith("WARMUP_INSUFFICIENT:")
            ):
                return err
    return None


def _extract_governance_action(raw: dict[str, Any] | None) -> str:
    if not raw:
        return "UNKNOWN"
    governance = raw.get("governance")
    if isinstance(governance, dict):
        action = governance.get("action")
        if isinstance(action, str) and action:
            return action
    reason = _extract_hold_block_reason(raw)
    if reason:
        if reason.startswith("GOVERNANCE_BLOCK"):
            return "BLOCK"
        if reason.startswith("GOVERNANCE_HOLD") or reason.startswith("WARMUP_INSUFFICIENT"):
            return "HOLD"
    return "ALLOW"


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

    # Inject staleness metadata
    data["_meta"] = _build_meta(data)

    return data


# --- PATCH 4: Verdict response filter + cache ---
import logging

logger = logging.getLogger(__name__)


class VerdictCache:
    """Simple in-memory cache to reduce Redis reads."""

    def __init__(self, ttl_seconds: float = 5.0) -> None:
        self._ttl = ttl_seconds
        self._data: dict[str, Any] | None = None
        self._last_fetch: float = 0.0

    @property
    def is_stale(self) -> bool:
        return (time.time() - self._last_fetch) > self._ttl

    def get(self) -> dict[str, Any] | None:
        if self.is_stale:
            return None
        return self._data

    def set(self, data: dict[str, Any]) -> None:
        self._data = data
        self._last_fetch = time.time()


_verdict_cache = VerdictCache(ttl_seconds=5.0)


def _filter_valid_verdicts(verdicts: dict[str, Any]) -> dict[str, Any]:
    valid = {}
    for pair, v in verdicts.items():
        score = v.get("score", 0)
        tp1 = v.get("take_profit_1", 0)
        sl = v.get("stop_loss", 0)
        direction = v.get("direction", "")
        if not score or score <= 0:
            continue
        if not tp1 or tp1 <= 0:
            continue
        if not sl or sl <= 0:
            continue
        if not direction or direction == "NEUTRAL":
            continue
        valid[pair] = v
    if len(valid) < len(verdicts):
        logger.debug(
            "[Verdict API] Filtered %d/%d invalid verdicts",
            len(verdicts) - len(valid),
            len(verdicts),
        )
    return valid


@router.get("/api/v1/verdict/all", dependencies=[Depends(verify_token)])
def fetch_all_verdicts() -> dict[str, Any]:
    """Get verdicts for all available pairs (filtered, cached)."""
    cached = _verdict_cache.get()
    if cached is not None:
        return {"verdicts": cached, "count": len(cached), "cached": True}
    verdicts: dict[str, Any] = {}
    for pair_info in AVAILABLE_PAIRS:
        pair = pair_info["symbol"]
        if not isinstance(pair, str):
            continue
        if not pair_info.get("enabled", True):
            continue
        data = get_verdict(pair)
        if data:
            score = data.get("score", 0)
            tp1 = data.get("take_profit_1", 0)
            if score > 0 and tp1 > 0:
                data["_meta"] = _build_meta(data)
                verdicts[pair] = data
    valid = _filter_valid_verdicts(verdicts)
    _verdict_cache.set(valid)
    return {"verdicts": valid, "count": len(valid), "cached": False}


@router.get("/api/v1/verdict", dependencies=[Depends(verify_token)])
def fetch_all_verdicts_alias() -> dict[str, Any]:
    """Compatibility alias: return verdicts for all available pairs."""
    return fetch_all_verdicts()


_STALE_THRESHOLD_SEC = 300.0  # 5 minutes


@router.get("/api/v1/verdict/health", dependencies=[Depends(verify_token)])
def verdict_health() -> dict[str, Any]:
    """P0 diagnostic: prove verdicts are being written.

    Returns per-pair verdict presence, freshness, and overall status.
    Zone: dashboard (monitoring/ops) — no market logic.
    """
    now = time.time()
    pairs_detail: list[dict[str, Any]] = []
    healthy = 0
    stale = 0
    missing = 0

    for pair_info in AVAILABLE_PAIRS:
        pair = pair_info["symbol"]
        if not isinstance(pair, str) or not pair_info.get("enabled", True):
            continue

        data = get_verdict(pair)
        if data is None:
            pairs_detail.append({"pair": pair, "status": "missing", "verdict": None, "age_seconds": None})
            missing += 1
            continue

        cached_at = data.get("_cached_at")
        age = round(now - float(cached_at), 3) if cached_at is not None else None
        stale_flag = is_verdict_stale(data, _STALE_THRESHOLD_SEC)

        if stale_flag:
            stale += 1
        else:
            healthy += 1

        pairs_detail.append(
            {
                "pair": pair,
                "status": "stale" if stale_flag else "ok",
                "verdict": data.get("verdict"),
                "confidence": data.get("confidence"),
                "age_seconds": age,
                "_cached_at": cached_at,
            }
        )

    total = healthy + stale + missing
    if missing == total:
        overall = "no_data"
    elif missing > 0 or (stale > 0 and healthy == 0):
        overall = "unhealthy"
    elif stale > 0:
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "status": overall,
        "summary": {"total": total, "healthy": healthy, "stale": stale, "missing": missing},
        "stale_threshold_seconds": _STALE_THRESHOLD_SEC,
        "checked_at": now,
        "pairs": pairs_detail,
    }


def _empty_context() -> dict[str, Any]:
    """Safe empty context — dashboard shows '—' instead of error banner."""
    ts = now_utc()
    return {
        "candles": {},
        "ticks": {},
        "conditioned_returns": {},
        "conditioning_meta": {},
        "macro": {},
        "news": {},
        "inference": {
            "regime_state": {},
            "volatility_regime": "UNKNOWN",
            "session_state": {},
            "liquidity_map": {},
            "news_pressure_vector": {},
            "signal_stack": [],
            "inference_ts": 0,
        },
        "meta": {"inference_ts": 0, "volatility_regime": "UNKNOWN"},
        "active_pairs": 0,
        "timestamp_utc": format_utc(ts),
        "timestamp_local": format_local(ts),
        "feed_status": "UNKNOWN",
        "feed_staleness_seconds": None,
        "feed_threshold_seconds": None,
        "feed_last_seen_ts": None,
        "feed_detail": {},
    }


def _count_active_pairs(reader: RedisContextReader) -> int:
    """Count symbols with at least one ready warmup timeframe."""
    ws = reader.warmup_state
    return sum(1 for s in ws.get("symbols", {}).values() if s.get("ready"))


@router.get("/api/v1/context", dependencies=[Depends(verify_token)])
async def fetch_context() -> dict[str, Any]:
    """Get live context snapshot."""
    import math  # noqa: PLC0415

    from loguru import logger  # noqa: PLC0415

    from .allocation_router import _feed_freshness_snapshot  # noqa: PLC0415

    try:
        reader = RedisContextReader()
        snapshot = reader.snapshot()
        # Ensure active_pairs is always present for dashboard Header.tsx
        if "active_pairs" not in snapshot:
            snapshot["active_pairs"] = _count_active_pairs(reader)
    except Exception as exc:
        logger.warning("/api/v1/context snapshot fallback: {}", exc)
        return _empty_context()

    try:
        feed_snapshot = await _feed_freshness_snapshot()
    except Exception as exc:
        # Context data available but feed freshness failed — still return context
        logger.warning("/api/v1/context feed fallback: {}", exc)
        current_time = now_utc()
        snapshot["timestamp_utc"] = format_utc(current_time)
        snapshot["timestamp_local"] = format_local(current_time)
        snapshot["feed_status"] = "UNKNOWN"
        snapshot["feed_staleness_seconds"] = None
        snapshot["feed_threshold_seconds"] = None
        snapshot["feed_last_seen_ts"] = None
        snapshot["feed_detail"] = {}
        return snapshot

    # Add timestamp info
    current_time = now_utc()
    snapshot["timestamp_utc"] = format_utc(current_time)
    snapshot["timestamp_local"] = format_local(current_time)
    snapshot["feed_status"] = feed_snapshot.state
    # Sanitize non-finite floats — json.dumps emits bare ``Infinity``/``NaN``
    # which are not valid JSON and cause JSON.parse failures in the dashboard.
    staleness = feed_snapshot.staleness_seconds
    snapshot["feed_staleness_seconds"] = staleness if math.isfinite(staleness) else None
    snapshot["feed_threshold_seconds"] = feed_snapshot.threshold_seconds
    snapshot["feed_last_seen_ts"] = feed_snapshot.last_seen_ts
    snapshot["feed_detail"] = feed_snapshot.detail

    return snapshot


@router.get("/api/v1/execution", dependencies=[Depends(verify_token)])
def fetch_execution() -> dict[str, Any]:
    """Get current execution state for all tracked symbols."""
    registry = ExecutionStateMachine()
    execution_state = registry.snapshot_all()

    # Add timezone info
    current_time = now_utc()

    return {
        "symbols": execution_state,
        "current_time_utc": format_utc(current_time),
        "current_time_local": format_local(current_time),
    }


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
    {"id": "L1", "name": "Context", "zone": "COG"},
    {"id": "L2", "name": "MTA", "zone": "COG"},
    {"id": "L3", "name": "Technical", "zone": "ANA"},
    {"id": "L4", "name": "Scoring", "zone": "ANA"},
    {"id": "L5", "name": "Psychology", "zone": "META"},
    {"id": "L6", "name": "Risk", "zone": "META"},
    {"id": "L7", "name": "Monte Carlo", "zone": "ANA"},
    {"id": "L8", "name": "TII", "zone": "ANA"},
    {"id": "L9", "name": "SMC/VP", "zone": "ANA"},
    {"id": "L10", "name": "Position", "zone": "EXEC"},
    {"id": "L11", "name": "Execution", "zone": "EXEC"},
    {"id": "L12", "name": "Verdict", "zone": "VER"},
    {"id": "L13", "name": "Reflect", "zone": "POST"},
    {"id": "L14", "name": "Export", "zone": "POST"},
    {"id": "L15", "name": "Sovereign", "zone": "POST"},
]

_DEFAULT_DAG_EDGES: list[dict[str, str]] = [
    {"from": "L1", "to": "L4"},
    {"from": "L2", "to": "L4"},
    {"from": "L3", "to": "L4"},
    {"from": "L2", "to": "L5"},
    {"from": "L4", "to": "L7"},
    {"from": "L5", "to": "L7"},
    {"from": "L4", "to": "L8"},
    {"from": "L4", "to": "L9"},
    {"from": "L3", "to": "L11"},
    {"from": "L11", "to": "L6"},
    {"from": "L6", "to": "L10"},
    {"from": "L1", "to": "macro"},
    {"from": "L2", "to": "macro"},
    {"from": "L3", "to": "macro"},
    {"from": "L10", "to": "L12"},
    {"from": "L7", "to": "L12"},
    {"from": "L8", "to": "L12"},
    {"from": "L9", "to": "L12"},
    {"from": "L6", "to": "L12"},
    {"from": "macro", "to": "L12"},
    {"from": "L12", "to": "L13"},
    {"from": "L13", "to": "L15"},
    {"from": "L15", "to": "L14"},
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
    latency: int = int(verdict_data.get("system", {}).get("latency_ms", 0) or gates_raw.get("gate_8_latency_val", 0))

    # ── Build gate array ──────────────────────────────────────────────────
    gate_list: list[dict[str, Any]] = []
    for key, label in _GATE_LABELS.items():
        gate_val = gates_raw.get(key)
        passed = gate_val == "PASS" if isinstance(gate_val, str) else bool(gate_val)
        gate_list.append(
            {
                "name": label,
                "val": gate_val if gate_val is not None else "—",
                "thr": "—",
                "pass": passed,
            }
        )

    # ── Build layer array with available scores ───────────────────────────
    # Map known score keys to layer IDs
    layer_score_map: dict[str, tuple[str, str]] = {
        "L7": (str(layers_raw.get("L7_monte_carlo_win", "—")), "MC"),
        "L8": (str(scores.get("tii", layers_raw.get("L8_tii_sym", "—"))), "integ"),
        "L12": (
            f"{gates_raw.get('passed', '?')}/{gates_raw.get('total', '?')}",
            verdict_str.split("_")[0] if "_" in verdict_str else verdict_str,
        ),
    }

    pass_count = int(gates_raw.get("passed", 0))
    total_gates = int(gates_raw.get("total", 9))

    layer_list: list[dict[str, Any]] = []
    for ldef in _LAYER_DEFS:
        lid = ldef["id"]
        val, detail = layer_score_map.get(lid, ("—", "—"))
        # Determine status from gate results or default
        if lid == "L12":
            status = "pass" if pass_count == total_gates else ("warn" if pass_count >= 7 else "fail")
        else:
            status = "pass"  # default — layers don't have individual pass/fail in cache
        layer_list.append(
            {
                "id": lid,
                "name": ldef["name"],
                "zone": ldef["zone"],
                "status": status,
                "val": val,
                "detail": detail,
            }
        )

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
        execution_map: dict[str, Any] = cast(dict[str, Any], execution_map_raw)
    else:
        execution_map = {
            "pair": pair,
            "timestamp": verdict_data.get("timestamp", ""),
            "layers_executed": [layer["id"] for layer in layer_list],
            "engines_invoked": [],
            "halt_reason": None,
            "constitutional_verdict": verdict_str,
        }

    system_raw: dict[str, Any] = verdict_data.get("system", {})
    layer_timings_raw = execution_map.get("layer_timings_ms", system_raw.get("layer_timings_ms", {}))
    if isinstance(layer_timings_raw, dict):
        layer_timings_dict = cast(dict[str, Any], layer_timings_raw)
        layer_timings_ms: dict[str, float] = {}
        for k, v in layer_timings_dict.items():
            if isinstance(v, int | float | str):
                with contextlib.suppress(TypeError, ValueError):
                    layer_timings_ms[k] = float(v)
    else:
        layer_timings_ms: dict[str, float] = {}

    dag_raw = execution_map.get("dag", system_raw.get("dag", {}))
    if isinstance(dag_raw, dict):
        dag_payload = cast(dict[str, Any], dag_raw)
        dag_topology = dag_payload.get("topology", [])
        dag_batches = dag_payload.get("batches", [])
        dag_edges = dag_payload.get("edges", _DEFAULT_DAG_EDGES)
    else:
        dag_topology = []
        dag_batches = []
        dag_edges = _DEFAULT_DAG_EDGES

    if not isinstance(dag_topology, list):
        dag_topology = []
    if not isinstance(dag_batches, list):
        dag_batches = []
    if not isinstance(dag_edges, list):
        dag_edges = _DEFAULT_DAG_EDGES

    dag_edges_list = cast(list[Any], dag_edges)
    dag_edges_typed: list[dict[str, Any]] = [
        cast(dict[str, Any], edge) for edge in dag_edges_list if isinstance(edge, dict)
    ]

    deps_by_target: dict[str, list[str]] = {}
    for edge in dag_edges_typed:
        src = str(edge.get("from", "")).strip()
        dst = str(edge.get("to", "")).strip()
        if not src or not dst:
            continue
        deps_by_target.setdefault(dst, []).append(src)

    for layer in layer_list:
        lid = layer["id"]
        timing = layer_timings_ms.get(lid)
        layer["timingMs"] = round(float(timing), 3) if timing is not None else None
        layer["deps"] = sorted(set(deps_by_target.get(lid, [])))

    dag_nodes = [
        {
            "id": ldef["id"],
            "name": ldef["name"],
            "zone": ldef["zone"],
            "status": next((layer["status"] for layer in layer_list if layer["id"] == ldef["id"]), "pass"),
            "timingMs": layer_timings_ms.get(ldef["id"]),
        }
        for ldef in _LAYER_DEFS
    ]

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
        "profiling": {
            "layer_timings_ms": layer_timings_ms,
            "total_latency_ms": latency,
        },
        "observability": {
            "signal_conditioning": verdict_data.get("system", {}).get("signal_conditioning", {}),
        },
        "dag": {
            "nodes": dag_nodes,
            "edges": dag_edges,
            "topology": dag_topology,
            "batches": dag_batches,
        },
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


@router.get("/api/v1/internal/verdict/path", dependencies=[Depends(verify_token)])
def fetch_internal_verdict_path(pair: str | None = None) -> dict[str, Any]:
    """Internal runtime debug for verdict path health and recency."""
    context_bus = cast(Any, RedisContextReader())
    available_symbols = [str(p["symbol"]).upper() for p in AVAILABLE_PAIRS if isinstance(p.get("symbol"), str)]
    enabled_symbols = [
        str(p["symbol"]).upper()
        for p in AVAILABLE_PAIRS
        if isinstance(p.get("symbol"), str) and bool(p.get("enabled", True))
    ]
    targets = [pair.upper()] if pair else enabled_symbols
    redis_error: str | None = None

    rows: list[dict[str, Any]] = []
    for symbol in targets:
        raw: dict[str, Any] | None = None
        try:
            raw = get_verdict(symbol)
        except Exception as exc:
            redis_error = str(exc)
        warmup = context_bus.check_warmup(symbol, _WARMUP_MIN_BARS)
        ts_raw = (raw or {}).get("_cached_at") if raw else None
        if ts_raw is None and raw:
            ts_raw = raw.get("timestamp")
        verdict_ts: float | None = None
        if isinstance(ts_raw, int | float):
            verdict_ts = float(ts_raw)
        elif isinstance(ts_raw, str) and ts_raw.strip():
            with contextlib.suppress(ValueError):
                verdict_ts = float(ts_raw)
        age_sec = round(time.time() - verdict_ts, 3) if verdict_ts is not None else None
        rows.append(
            {
                "pair": symbol,
                "active_pair": symbol in enabled_symbols,
                "configured_pair": symbol in available_symbols,
                "redis_key": f"{KEY_PREFIX}{symbol}",
                "redis_key_exists": raw is not None,
                "warmup_status": {
                    "ready": bool(warmup.get("ready", False)),
                    "bars": warmup.get("bars", {}),
                    "required": warmup.get("required", {}),
                    "missing": warmup.get("missing", {}),
                },
                "governance_action": _extract_governance_action(raw),
                "last_verdict": (raw or {}).get("verdict"),
                "last_verdict_timestamp": verdict_ts,
                "verdict_age_seconds": age_sec,
                "last_hold_block_reason": _extract_hold_block_reason(raw),
            }
        )

    return {
        "generated_at": time.time(),
        "requested_pair": pair.upper() if pair else None,
        "redis_ok": redis_error is None,
        "redis_error": redis_error,
        "pairs": rows,
    }
