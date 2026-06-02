"""Non-mutating tradeplan enrichment for emitted SignalJSON events.

This module intentionally sits after signal classification and lifecycle
decisions. It may complete output metadata and execution readiness, but it
must never change analytical status, direction, action, or L12 state.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

TP1_RR_FLOOR = 2.0
STRUCTURE_RR_FLOOR = 2.5
_WITA = ZoneInfo("Asia/Makassar")
STRUCTURE_TARGET_MODES = {
    "FINAL_MARKET_STRUCTURE",
    "STRUCTURE_LADDER_TARGET",
    "KEY_LEVEL_STRUCTURE_TARGET",
}


def enrich_signal_json_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return an output-only decorated copy of a signal payload."""
    enriched = deepcopy(payload)
    _normalize_nested_output(enriched)
    direction = _direction(enriched.get("final_direction"))
    status = str(enriched.get("status") or "")
    if direction is None or not _is_directional_final(status):
        return enriched

    source_valid_for_execution = bool(
        enriched.get("source_valid_for_execution")
        if enriched.get("source_valid_for_execution") is not None
        else enriched.get("valid_for_execution", False)
    )
    source_target_mode = str(enriched.get("source_target_mode") or enriched.get("target_mode") or "") or None
    normalized_target_mode = str(enriched.get("target_mode") or "").upper()
    entry = _optional_float(enriched.get("entry_reference_price") or enriched.get("signal_valid_price"))
    pip_value = _pip_value(str(enriched.get("symbol") or ""))
    sl_safe = _valid_stop(direction, entry, _optional_float(enriched.get("sl_safe")))
    selected_sl = _valid_stop(direction, entry, _optional_float(enriched.get("selected_sl"))) or sl_safe
    selected_mode = "SAFE" if selected_sl is not None else None
    selected_risk = _risk_pips(entry, selected_sl, pip_value)
    tp1 = _rr_target(direction, entry, selected_sl, TP1_RR_FLOOR)

    zones = dict(enriched["structure_zones"])
    key_resistance = _first_float(zones.get("key_resistance"), enriched.get("key_resistance"), enriched.get("breakout_reclaim_level"))
    key_support = _first_float(zones.get("key_support"), enriched.get("key_support"), enriched.get("support_reclaim_level"))
    zones.update(
        {
            "price_position": enriched.get("price_position"),
            "key_resistance": key_resistance,
            "key_support": key_support,
            "entry_zone": enriched.get("entry_zone"),
        }
    )
    if direction == "BUY":
        zones["breakout_zone"] = enriched.get("breakout_buy_zone") or enriched.get("entry_zone")
    else:
        zones["rejection_zone"] = enriched.get("sell_rejection_zone") or enriched.get("entry_zone")

    targets = _targets(direction, entry, selected_sl, tp1, enriched)
    has_structure_target = any(item["type"] == "STRUCTURE_TARGET" for item in targets)
    target_policy = {
        "mode": "TP1_FIXED_RR_THEN_STRUCTURE_TARGETS",
        "tp1_rr": TP1_RR_FLOOR,
        "tp1_required": True,
        "tp2_plus_source": "OBSERVED_KEY_STRUCTURE_LEVELS_ONLY",
        "allow_variable_tp_count": True,
        "min_structure_rr_required": STRUCTURE_RR_FLOOR,
    }
    expiry = _expiry(enriched)
    execution_quality = dict(enriched["execution_quality"])
    execution_quality.setdefault("spread_normal", enriched.get("spread_normal"))
    execution_quality.setdefault("spread_pips", enriched.get("spread_pips"))
    execution_quality.setdefault("max_allowed_spread_pips", enriched.get("max_allowed_spread_pips"))
    phase_coherence = _phase_coherence(enriched, direction)
    tp_min_rr = _rr_target(direction, entry, selected_sl, STRUCTURE_RR_FLOOR)
    tradeplan_valid = bool(
        entry is not None
        and selected_sl is not None
        and key_resistance is not None
        and key_support is not None
        and has_structure_target
    )
    execution_valid_now = bool(
        source_valid_for_execution
        and tradeplan_valid
        and execution_quality.get("spread_normal") is True
        and phase_coherence.get("status") == "EXECUTION_COMPATIBLE"
        and expiry is not None
    )

    enriched.update(
        {
            "source_valid_for_execution": source_valid_for_execution,
            "source_target_mode": source_target_mode,
            "direction_valid": True,
            "analysis_valid": True,
            "tradeplan_valid": tradeplan_valid,
            "execution_valid_now": execution_valid_now,
            "valid_for_execution": execution_valid_now,
            "execution_status": "EXECUTION_VALID_NOW" if execution_valid_now else "WAIT_STRUCTURE_COMPLETION",
            "execution_reason": (
                "structure_risk_quality_and_phase_contract_complete"
                if execution_valid_now
                else "direction_preserved_but_structure_aware_tradeplan_or_execution_quality_incomplete"
            ),
            "selected_sl_mode": selected_mode if selected_sl is not None else None,
            "selected_sl": selected_sl,
            "risk_pips": selected_risk,
            "risk_pips_safe": _risk_pips(entry, sl_safe, pip_value),
            "selected_risk_pips": selected_risk,
            "target_mode": (
                normalized_target_mode
                if tradeplan_valid and normalized_target_mode in STRUCTURE_TARGET_MODES
                else ("STRUCTURE_LADDER_TARGET" if tradeplan_valid else "STRUCTURE_ENRICHMENT_PENDING")
            ),
            "target_policy": target_policy,
            "targets": targets,
            "structure_zones": zones,
            "risk_reward": {
                "entry": entry,
                "sl_tight": sl_tight,
                "sl_safe": sl_safe,
                "selected_sl": selected_sl,
                "risk_pips_tight": _risk_pips(entry, sl_tight, pip_value),
                "risk_pips_safe": _risk_pips(entry, sl_safe, pip_value),
                "selected_risk_pips": selected_risk,
                "tp1_rr": TP1_RR_FLOOR,
                "tp_min_rr": tp_min_rr,
                "min_structure_rr_required": STRUCTURE_RR_FLOOR,
                "rr_status": "VALID" if tradeplan_valid else "WAIT_STRUCTURE_TARGET",
            },
            "tp1": tp1,
            "tp2": targets[1]["level"] if len(targets) > 1 else None,
            "tp3": targets[2]["level"] if len(targets) > 2 else None,
            "tp4": targets[3]["level"] if len(targets) > 3 else None,
            "tp1_rr": TP1_RR_FLOOR if tp1 is not None else None,
            "tp2_rr": targets[1]["rr"] if len(targets) > 1 else None,
            "tp3_rr": targets[2]["rr"] if len(targets) > 2 else None,
            "tp4_rr": targets[3]["rr"] if len(targets) > 3 else None,
            "rr_status": "VALID" if tradeplan_valid else "WATCH_PROVISIONAL",
            "tp_min_rr": tp_min_rr,
            "tp_min_rr_value": STRUCTURE_RR_FLOOR,
            "invalidation_rules": {
                "hard_invalid_level": selected_sl,
                "direction": direction,
                "rule": "STRUCTURE_RECLAIM_BEYOND_SELECTED_STOP",
            },
            "execution_quality": execution_quality,
            "phase_coherence": phase_coherence,
            "signal_expiry": expiry or {},
        }
    )
    return enriched


def _normalize_nested_output(payload: dict[str, Any]) -> None:
    """Guarantee safe nested containers for watch, update, and final logs."""
    payload["targets"] = (
        [dict(item) for item in payload["targets"] if isinstance(item, dict)]
        if isinstance(payload.get("targets"), list)
        else []
    )
    payload["target_policy"] = (
        dict(payload["target_policy"])
        if isinstance(payload.get("target_policy"), dict)
        else {
            "mode": str(payload.get("target_mode") or "PENDING_STRUCTURE"),
            "tp1_rr": TP1_RR_FLOOR,
            "tp2_plus_source": "OBSERVED_KEY_STRUCTURE_LEVELS_ONLY",
        }
    )
    payload["structure_zones"] = (
        dict(payload["structure_zones"]) if isinstance(payload.get("structure_zones"), dict) else {}
    )
    payload["risk_reward"] = (
        dict(payload["risk_reward"]) if isinstance(payload.get("risk_reward"), dict) else {}
    )
    payload["invalidation_rules"] = (
        dict(payload["invalidation_rules"]) if isinstance(payload.get("invalidation_rules"), dict) else {}
    )
    payload["execution_quality"] = (
        dict(payload["execution_quality"]) if isinstance(payload.get("execution_quality"), dict) else {}
    )
    payload["phase_coherence"] = (
        dict(payload["phase_coherence"]) if isinstance(payload.get("phase_coherence"), dict) else {}
    )
    payload["signal_expiry"] = (
        dict(payload["signal_expiry"]) if isinstance(payload.get("signal_expiry"), dict) else {}
    )
    payload["audit_block_reasons"] = (
        [str(reason) for reason in payload["audit_block_reasons"]]
        if isinstance(payload.get("audit_block_reasons"), list)
        else []
    )


def _targets(
    direction: str,
    entry: float | None,
    selected_sl: float | None,
    tp1: float | None,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    if tp1 is not None:
        targets.append(
            {
                "id": "TP1",
                "level": tp1,
                "type": "FIXED_RR",
                "source": "MANDATORY_TP1_RR_FLOOR",
                "rr": TP1_RR_FLOOR,
                "required": True,
            }
        )
    if str(payload.get("target_mode") or "").upper() not in STRUCTURE_TARGET_MODES:
        return targets

    candidates: list[float] = []
    raw_targets = payload.get("targets")
    if isinstance(raw_targets, list) and raw_targets:
        for item in raw_targets:
            if isinstance(item, dict) and str(item.get("type") or "").upper() != "FIXED_RR":
                level = _optional_float(item.get("level"))
                if level is not None:
                    candidates.append(level)
    else:
        candidates.extend(
            level
            for key in ("tp1", "tp2", "tp3", "tp4")
            if (level := _optional_float(payload.get(key))) is not None
        )
    for level in sorted(set(candidates), reverse=direction == "SELL"):
        rr = _rr(direction, entry, selected_sl, level)
        if rr is None or rr < STRUCTURE_RR_FLOOR or level == tp1:
            continue
        targets.append(
            {
                "id": f"TP{len(targets) + 1}",
                "level": level,
                "type": "STRUCTURE_TARGET",
                "source": "OBSERVED_STRUCTURE_LADDER",
                "rr": rr,
                "required": False,
            }
        )
    return targets


def _phase_coherence(payload: dict[str, Any], direction: str) -> dict[str, Any]:
    existing = dict(payload["phase_coherence"])
    m15 = existing.get("m15") or payload.get("m15_phase")
    h1 = existing.get("h1") or payload.get("h1_phase")
    aligned = _phase_direction(m15) == direction and _phase_direction(h1) == direction
    existing.update({"m15": m15, "h1": h1, "status": "EXECUTION_COMPATIBLE" if aligned else "EXECUTION_REVIEW_REQUIRED"})
    return existing


def _expiry(payload: dict[str, Any]) -> dict[str, Any] | None:
    existing = payload.get("signal_expiry")
    if isinstance(existing, dict) and existing.get("expires_at_utc"):
        return dict(existing)
    raw = str(payload.get("signal_valid_time_utc") or "").strip()
    if not raw:
        return None
    try:
        signal_time = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    minutes = 45 if "CONTINUATION" in str(payload.get("status") or "") else 30
    expires = signal_time + timedelta(minutes=minutes)
    return {
        "valid_minutes": minutes,
        "expires_at_utc": expires.isoformat(),
        "expires_at_wita": expires.astimezone(_WITA).strftime("%Y-%m-%d %H:%M:%S"),
        "requires_revalidation_after_minutes": min(15, minutes),
    }


def _direction(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    return text if text in {"BUY", "SELL"} else None


def _is_directional_final(status: str) -> bool:
    return status.endswith("_VALID") or status.endswith("_CONTINUATION") or "_VALID_BY_" in status


def _phase_direction(value: Any) -> str | None:
    text = str(value or "").upper()
    if "BULLISH" in text or text == "BUY":
        return "BUY"
    if "BEARISH" in text or text == "SELL":
        return "SELL"
    return None


def _pip_value(symbol: str) -> float:
    return 0.01 if "JPY" in symbol.upper() else 0.0001


def _valid_stop(direction: str, entry: float | None, value: float | None) -> float | None:
    if entry is None or value is None:
        return None
    if (direction == "BUY" and value < entry) or (direction == "SELL" and value > entry):
        return value
    return None


def _risk_pips(entry: float | None, stop: float | None, pip_value: float) -> float | None:
    if entry is None or stop is None:
        return None
    return round(abs(entry - stop) / pip_value, 1)


def _rr_target(direction: str, entry: float | None, sl: float | None, rr: float) -> float | None:
    if entry is None or sl is None:
        return None
    reward = abs(entry - sl) * rr
    return round(entry + reward if direction == "BUY" else entry - reward, 5)


def _rr(direction: str, entry: float | None, sl: float | None, target: float | None) -> float | None:
    if entry is None or sl is None or target is None:
        return None
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    reward = target - entry if direction == "BUY" else entry - target
    return round(reward / risk, 2)


def _first_float(*values: Any) -> float | None:
    for value in values:
        number = _optional_float(value)
        if number is not None:
            return number
    return None


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
