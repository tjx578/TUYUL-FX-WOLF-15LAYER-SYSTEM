"""Diagnostic pressure-tier ranking for SignalThrottle analysis.

Pressure tiers are an observability and dashboard-routing layer.  They never
grant execution permission, never resolve final direction, and never mutate
trade plan fields.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

TIER_1_PRIMARY_ANALYSIS = "TIER_1_PRIMARY_ANALYSIS"
TIER_2_CONFIRMATION_SUPPORT = "TIER_2_CONFIRMATION_SUPPORT"
TIER_3_THEME_RADAR = "TIER_3_THEME_RADAR"
TIER_3_KEY_LEVEL_RADAR_EXCEPTION = "TIER_3_KEY_LEVEL_RADAR_EXCEPTION"
TIER_FRAGMENTED_PRESSURE_RADAR = "FRAGMENTED_PRESSURE_RADAR"
TIER_PRESSURE_MEMORY_RADAR = "PRESSURE_MEMORY_RADAR"
TIER_THEME_ROTATION_RADAR = "THEME_ROTATION_RADAR"
TIER_STALE_ARCHIVE = "TIER_STALE_ARCHIVE"
TIER_UNSAFE_MIXED_DEPLOYMENT = "TIER_UNSAFE_MIXED_DEPLOYMENT"
TIER_NONE = "TIER_NONE"
IMPACT_TIER_1_KEY_LEVEL = "IMPACT_TIER_1_KEY_LEVEL"

LIVE_SCOPE = "LIVE_120M"
SESSION_SCOPE = "SESSION_24H"
ARCHIVE_SCOPE = "ARCHIVE"
NONE_SCOPE = "NONE"

_CURRENCIES = ("AUD", "CAD", "CHF", "EUR", "GBP", "JPY", "NZD", "USD")
_METAL_BASES = ("XAG", "XAU")
_EXECUTION_IMPACT = False
_VISIBLE_WATCH_TIERS = {TIER_1_PRIMARY_ANALYSIS, TIER_2_CONFIRMATION_SUPPORT}
_KEY_LEVEL_PRICE_POSITIONS = {"MAIN_SUPPORT", "MAIN_RESISTANCE"}
_TIER_SOURCE_EVENT = "SignalThrottlePressureTierSnapshot"
_LOG_SCHEMA_VERSION = "1.1-pressure-tier"


@dataclass(frozen=True)
class _ScopeMetrics:
    symbol: str
    scope: str
    event_count: int
    effective_ticks: int
    latest_event_age_seconds: float | None
    clean_block_duration_seconds: float
    clean_block_age_seconds: float | None
    effective_density_per_minute: float
    direction: str | None
    direction_purity: float
    lifecycle_role: str | None
    theme_aligned: bool
    run_count: int
    same_symbol_reentry_count: int
    interrupted_by_other_symbols: bool
    clean_block_count: int
    max_clean_block_minutes: float
    fragmented_event_count: int
    pressure_memory_score: float
    score: float
    reasons: tuple[str, ...]


def build_pressure_tier_snapshot(
    events: Iterable[Any],
    *,
    blocks: Iterable[Any] | None = None,
    symbol_activity: Mapping[str, Mapping[str, Any]] | None = None,
    clean_watch_candidates: Sequence[Mapping[str, Any]] | None = None,
    candidate_lifecycle: Mapping[str, Any] | None = None,
    theme_scores: Sequence[Mapping[str, Any]] | None = None,
    clean_block_seconds: int = 300,
    live_window_seconds: int = 7200,
    session_window_seconds: int = 86400,
    deployment_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build a diagnostic-only priority ranking for pressure analysis."""

    ordered = sorted(list(events), key=_event_timestamp)
    ordered_blocks = sorted(list(blocks or []), key=_block_end)
    deployment_id_list = sorted({item for item in (_clean_text(value) for value in deployment_ids or []) if item})
    generated_at = _event_timestamp(ordered[-1]) if ordered else datetime.now(UTC)
    scope_config = {
        "live_window_seconds": int(live_window_seconds),
        "session_window_seconds": int(session_window_seconds),
        "clean_block_seconds": int(clean_block_seconds),
    }

    if not ordered:
        return _snapshot_payload(
            generated_at=generated_at,
            symbols=[],
            deployment_ids=deployment_id_list,
            scope_config=scope_config,
            mixed_deployment=False,
        )

    symbols = _all_symbols(
        ordered,
        symbol_activity=symbol_activity,
        clean_watch_candidates=clean_watch_candidates,
        candidate_lifecycle=candidate_lifecycle,
    )
    mixed_deployment = len(deployment_id_list) > 1
    if mixed_deployment:
        rows = [_unsafe_symbol_row(symbol, deployment_id_list) for symbol in symbols]
        return _snapshot_payload(
            generated_at=generated_at,
            symbols=rows,
            deployment_ids=deployment_id_list,
            scope_config=scope_config,
            mixed_deployment=True,
        )

    live_cutoff = generated_at - timedelta(seconds=live_window_seconds)
    session_cutoff = generated_at - timedelta(seconds=session_window_seconds)
    scope_events = {
        LIVE_SCOPE: [event for event in ordered if _event_timestamp(event) >= live_cutoff],
        SESSION_SCOPE: [event for event in ordered if _event_timestamp(event) >= session_cutoff],
        ARCHIVE_SCOPE: ordered,
    }
    scope_blocks = {
        LIVE_SCOPE: [block for block in ordered_blocks if _block_end(block) >= live_cutoff],
        SESSION_SCOPE: [block for block in ordered_blocks if _block_end(block) >= session_cutoff],
        ARCHIVE_SCOPE: ordered_blocks,
    }

    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        live_metrics = _scope_metrics(
            symbol,
            LIVE_SCOPE,
            events=scope_events[LIVE_SCOPE],
            blocks=scope_blocks[LIVE_SCOPE],
            now=generated_at,
            clean_block_seconds=clean_block_seconds,
            candidate_lifecycle=candidate_lifecycle,
            theme_scores=theme_scores,
        )
        session_metrics = _scope_metrics(
            symbol,
            SESSION_SCOPE,
            events=scope_events[SESSION_SCOPE],
            blocks=scope_blocks[SESSION_SCOPE],
            now=generated_at,
            clean_block_seconds=clean_block_seconds,
            candidate_lifecycle=candidate_lifecycle,
            theme_scores=theme_scores,
        )
        archive_metrics = _scope_metrics(
            symbol,
            ARCHIVE_SCOPE,
            events=scope_events[ARCHIVE_SCOPE],
            blocks=scope_blocks[ARCHIVE_SCOPE],
            now=generated_at,
            clean_block_seconds=clean_block_seconds,
            candidate_lifecycle=candidate_lifecycle,
            theme_scores=theme_scores,
        )
        rows.append(_symbol_row(symbol, live_metrics, session_metrics, archive_metrics))

    rows.sort(key=_symbol_row_sort_key)
    return _snapshot_payload(
        generated_at=generated_at,
        symbols=rows,
        deployment_ids=deployment_id_list,
        scope_config=scope_config,
        mixed_deployment=False,
    )


def pressure_tier_snapshot_log_payload(
    snapshot: Mapping[str, Any] | None,
    *,
    max_symbols_per_tier: int = 12,
) -> dict[str, Any] | None:
    """Compact runtime log payload for global pressure-tier ranking."""

    if not isinstance(snapshot, Mapping):
        return None
    symbols = [row for row in snapshot.get("symbols") or [] if isinstance(row, Mapping)]
    tier_1 = [
        _compact_tier_row(row)
        for row in symbols
        if row.get("effective_pressure_tier") == TIER_1_PRIMARY_ANALYSIS
    ][:max_symbols_per_tier]
    tier_2 = [
        _compact_tier_row(row)
        for row in symbols
        if row.get("effective_pressure_tier") == TIER_2_CONFIRMATION_SUPPORT
    ][:max_symbols_per_tier]
    summary = {
        "tier_1": _tier_count(snapshot, "tier_1"),
        "tier_2": _tier_count(snapshot, "tier_2"),
        "tier_3_hidden": _tier_count(snapshot, "tier_3"),
        "stale_archive": _tier_count(snapshot, "stale_archive"),
        "unsafe_mixed_deployment": _tier_count(snapshot, "unsafe_mixed_deployment"),
    }
    display_line = _display_line(summary=summary, tier_1=tier_1, tier_2=tier_2)
    return {
        "event": "signal_throttle_pressure_tier_snapshot",
        "schema_version": _LOG_SCHEMA_VERSION,
        "scope": LIVE_SCOPE,
        "generated_at_utc": snapshot.get("generated_at_utc"),
        "mixed_deployment": bool(snapshot.get("mixed_deployment", False)),
        "deployment_ids": list(snapshot.get("deployment_ids") or []),
        "summary": summary,
        "display_line": display_line,
        "tier_1": tier_1,
        "tier_2": tier_2,
        "tier_3_hidden_count": summary["tier_3_hidden"],
        "stale_archive_count": summary["stale_archive"],
        "unsafe_mixed_deployment_count": summary["unsafe_mixed_deployment"],
        "visibility_policy": {
            "tier_1": "VISIBLE_IN_SNAPSHOT_AND_SIGNAL_WATCH_CONTEXT",
            "tier_2": "VISIBLE_IN_SNAPSHOT_AND_SIGNAL_WATCH_CONTEXT",
            "tier_3": "HIDDEN_FROM_SNAPSHOT_ROWS",
            "tier_3_exception": "SIGNAL_WATCH_KEY_LEVEL_CONTEXT_ONLY",
        },
        "execution_guard": {
            "observability_only": True,
            "signal_watch_context_only": True,
            "decision_update_tier_context_allowed": False,
            "signal_json_tier_context_allowed": False,
        },
        "tier_is_execution_signal": False,
        "tier_execution_impact": _EXECUTION_IMPACT,
    }


def pressure_priority_context_for_symbol(
    snapshot: Mapping[str, Any] | None,
    symbol: str,
    *,
    watch_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return local SignalWatch context inherited from the latest tier snapshot."""

    if not isinstance(snapshot, Mapping):
        return None
    if not _is_watch_payload(watch_payload):
        return None
    symbol_key = str(symbol or "").upper()
    if not symbol_key:
        return None
    row = _snapshot_row_for_symbol(snapshot, symbol_key)
    if row is None:
        return None

    tier = str(row.get("effective_pressure_tier") or "")
    if tier in _VISIBLE_WATCH_TIERS:
        return _watch_context_from_row(row, tier=tier)
    if tier == TIER_3_THEME_RADAR and _is_key_level_radar_exception(row, watch_payload or {}):
        return _watch_context_from_row(
            row,
            tier=TIER_3_KEY_LEVEL_RADAR_EXCEPTION,
            action="RADAR_EXCEPTION_ONLY",
            extra_reasons=_key_level_exception_reasons(row, watch_payload or {}),
            impact_tier=IMPACT_TIER_1_KEY_LEVEL,
            impact_reasons=_key_level_exception_reasons(row, watch_payload or {}),
            low_event_high_impact_candidate=True,
        )
    return None


def _snapshot_payload(
    *,
    generated_at: datetime,
    symbols: list[dict[str, Any]],
    deployment_ids: list[str],
    scope_config: dict[str, int],
    mixed_deployment: bool,
) -> dict[str, Any]:
    tiers = {
        "tier_1": [
            row["symbol"] for row in symbols if row.get("effective_pressure_tier") == TIER_1_PRIMARY_ANALYSIS
        ],
        "tier_2": [
            row["symbol"] for row in symbols if row.get("effective_pressure_tier") == TIER_2_CONFIRMATION_SUPPORT
        ],
        "tier_3": [row["symbol"] for row in symbols if row.get("effective_pressure_tier") == TIER_3_THEME_RADAR],
        "fragmented_pressure_radar": [
            row["symbol"] for row in symbols if row.get("effective_pressure_tier") == TIER_FRAGMENTED_PRESSURE_RADAR
        ],
        "pressure_memory_radar": [
            row["symbol"] for row in symbols if row.get("effective_pressure_tier") == TIER_PRESSURE_MEMORY_RADAR
        ],
        "theme_rotation_radar": [
            row["symbol"] for row in symbols if row.get("effective_pressure_tier") == TIER_THEME_ROTATION_RADAR
        ],
        "stale_archive": [row["symbol"] for row in symbols if row.get("effective_pressure_tier") == TIER_STALE_ARCHIVE],
        "unsafe_mixed_deployment": [
            row["symbol"] for row in symbols if row.get("effective_pressure_tier") == TIER_UNSAFE_MIXED_DEPLOYMENT
        ],
    }
    return {
        "enabled": True,
        "generated_at_utc": generated_at.isoformat(),
        "mixed_deployment": bool(mixed_deployment),
        "deployment_ids": deployment_ids,
        "scope_config": scope_config,
        "tier_is_execution_signal": False,
        "tier_execution_impact": _EXECUTION_IMPACT,
        "tiers": tiers,
        "summary": {key: len(value) for key, value in tiers.items()},
        "symbols": symbols,
    }


def _symbol_row(
    symbol: str,
    live_metrics: _ScopeMetrics,
    session_metrics: _ScopeMetrics,
    archive_metrics: _ScopeMetrics,
) -> dict[str, Any]:
    live_tier = _tier_for_metrics(live_metrics)
    session_tier = _tier_for_metrics(session_metrics)
    archive_tier = _tier_for_metrics(archive_metrics)
    effective_tier, scope, score, reasons = _effective_tier(
        live_tier,
        session_tier,
        archive_tier,
        live_metrics,
        session_metrics,
        archive_metrics,
    )
    direction = live_metrics.direction or session_metrics.direction or archive_metrics.direction
    effective_metrics = _metrics_for_scope(scope, live_metrics, session_metrics, archive_metrics)
    return {
        "symbol": symbol,
        "direction": direction,
        "pressure_tier_live": live_tier,
        "pressure_tier_session": session_tier,
        "pressure_tier_archive": archive_tier,
        "effective_pressure_tier": effective_tier,
        "tier_scope": scope,
        "tier_score": round(score, 3),
        "tier_reasons": reasons,
        "tier_action": _tier_action(effective_tier),
        "tier_family": _tier_family(effective_tier),
        "clean_block_required_for_tier_1": True,
        "pure_signal_throttle_tier": "CLEAN_BLOCK_TIER_1" if effective_tier == TIER_1_PRIMARY_ANALYSIS else None,
        "tier_stale": effective_tier == TIER_STALE_ARCHIVE,
        "tier_is_execution_signal": False,
        "tier_execution_impact": _EXECUTION_IMPACT,
        "fragmented_pressure_memory": _fragmented_memory_payload(effective_metrics),
        "metrics": {
            "live": _metrics_payload(live_metrics),
            "session": _metrics_payload(session_metrics),
            "archive": _metrics_payload(archive_metrics),
        },
    }


def _unsafe_symbol_row(symbol: str, deployment_ids: list[str]) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "direction": None,
        "pressure_tier_live": TIER_UNSAFE_MIXED_DEPLOYMENT,
        "pressure_tier_session": TIER_UNSAFE_MIXED_DEPLOYMENT,
        "pressure_tier_archive": TIER_UNSAFE_MIXED_DEPLOYMENT,
        "effective_pressure_tier": TIER_UNSAFE_MIXED_DEPLOYMENT,
        "tier_scope": NONE_SCOPE,
        "tier_score": 0.0,
        "tier_reasons": ["MULTIPLE_DEPLOYMENTS_IN_SOURCE_WINDOW", f"DEPLOYMENT_COUNT_{len(deployment_ids)}"],
        "tier_action": "DO_NOT_RANK",
        "tier_stale": False,
        "tier_is_execution_signal": False,
        "tier_execution_impact": _EXECUTION_IMPACT,
        "metrics": {},
    }


def _compact_tier_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "symbol": str(row.get("symbol") or "").upper(),
        "effective_pressure_tier": row.get("effective_pressure_tier"),
        "dominant_direction": row.get("direction"),
        "tier_scope": row.get("tier_scope"),
        "tier_score": row.get("tier_score"),
        "tier_action": row.get("tier_action"),
        "tier_reason_codes": _tier_reason_codes(row),
        "event_count": _metric_value(row, "event_count"),
        "clean_block_count": _metric_value(row, "clean_block_count"),
        "max_clean_block_minutes": _memory_value(row, "max_clean_block_minutes"),
        "pressure_memory_score": _memory_value(row, "pressure_memory_score"),
        "same_symbol_reentry_count": _memory_value(row, "same_symbol_reentry_count"),
        "tier_is_execution_signal": False,
        "tier_execution_impact": _EXECUTION_IMPACT,
    }


def _display_line(
    *,
    summary: Mapping[str, int],
    tier_1: Sequence[Mapping[str, Any]],
    tier_2: Sequence[Mapping[str, Any]],
) -> str:
    tier_1_labels = ", ".join(_display_symbol(row) for row in tier_1) or "-"
    tier_2_labels = ", ".join(_display_symbol(row) for row in tier_2) or "-"
    return (
        "pressure_tiers "
        f"tier1={summary.get('tier_1', 0)}[{tier_1_labels}] "
        f"tier2={summary.get('tier_2', 0)}[{tier_2_labels}] "
        f"tier3_hidden={summary.get('tier_3_hidden', 0)} "
        f"stale={summary.get('stale_archive', 0)} "
        f"unsafe_mixed={summary.get('unsafe_mixed_deployment', 0)} "
        "execution_impact=false"
    )


def _display_symbol(row: Mapping[str, Any]) -> str:
    symbol = str(row.get("symbol") or "").upper() or "UNKNOWN"
    direction = str(row.get("dominant_direction") or "NONE").upper()
    score = row.get("tier_score")
    try:
        score_text = f"{float(score):.1f}"
    except (TypeError, ValueError):
        score_text = "-"
    return f"{symbol}:{direction}:{score_text}"


def _metric_value(row: Mapping[str, Any], key: str) -> Any:
    metrics = row.get("metrics")
    if not isinstance(metrics, Mapping):
        return None
    scope = str(row.get("tier_scope") or LIVE_SCOPE).lower()
    metric_key = "live" if scope.startswith("live") else "session" if scope.startswith("session") else "archive"
    scoped = metrics.get(metric_key)
    if isinstance(scoped, Mapping):
        return scoped.get(key)
    return None


def _tier_reason_codes(row: Mapping[str, Any], limit: int = 6) -> list[str]:
    reasons = row.get("tier_reasons")
    if not isinstance(reasons, Sequence) or isinstance(reasons, (str, bytes)):
        return []
    deduped: list[str] = []
    for reason in reasons:
        text = str(reason or "").strip()
        if text and text not in deduped:
            deduped.append(text)
        if len(deduped) >= limit:
            break
    return deduped


def _tier_count(snapshot: Mapping[str, Any], key: str) -> int:
    summary = snapshot.get("summary")
    if isinstance(summary, Mapping):
        value = summary.get(key)
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0
    tiers = snapshot.get("tiers")
    values = tiers.get(key) if isinstance(tiers, Mapping) else []
    return len(values) if isinstance(values, list) else 0


def _memory_value(row: Mapping[str, Any], key: str) -> Any:
    memory = row.get("fragmented_pressure_memory")
    if isinstance(memory, Mapping):
        return memory.get(key)
    return None


def _snapshot_row_for_symbol(snapshot: Mapping[str, Any], symbol: str) -> Mapping[str, Any] | None:
    for row in snapshot.get("symbols") or []:
        if isinstance(row, Mapping) and str(row.get("symbol") or "").upper() == symbol:
            return row
    return None


def _metrics_for_scope(
    scope: str,
    live_metrics: _ScopeMetrics,
    session_metrics: _ScopeMetrics,
    archive_metrics: _ScopeMetrics,
) -> _ScopeMetrics:
    if scope == SESSION_SCOPE:
        return session_metrics
    if scope == ARCHIVE_SCOPE:
        return archive_metrics
    return live_metrics


def _fragmented_memory_payload(metrics: _ScopeMetrics) -> dict[str, Any]:
    return {
        "scope": metrics.scope,
        "fragmented_event_count": metrics.fragmented_event_count,
        "clean_block_count": metrics.clean_block_count,
        "max_clean_block_minutes": round(metrics.max_clean_block_minutes, 3),
        "same_symbol_reentry_count": metrics.same_symbol_reentry_count,
        "run_count": metrics.run_count,
        "interrupted_by_other_symbols": metrics.interrupted_by_other_symbols,
        "pressure_memory_score": round(metrics.pressure_memory_score, 3),
    }


def _watch_context_from_row(
    row: Mapping[str, Any],
    *,
    tier: str,
    action: str | None = None,
    extra_reasons: list[str] | None = None,
    impact_tier: str | None = None,
    impact_reasons: list[str] | None = None,
    low_event_high_impact_candidate: bool = False,
) -> dict[str, Any]:
    reasons = list(row.get("tier_reasons") or [])
    if extra_reasons:
        reasons.extend(extra_reasons)
    reasons = list(dict.fromkeys(str(reason) for reason in reasons if str(reason or "").strip()))
    context = {
        "effective_pressure_tier": tier,
        "tier_scope": row.get("tier_scope"),
        "tier_score": row.get("tier_score"),
        "tier_action": action or row.get("tier_action"),
        "tier_source_event": _TIER_SOURCE_EVENT,
        "tier_reason_codes": reasons[:8],
        "tier_is_execution_signal": False,
        "tier_execution_impact": _EXECUTION_IMPACT,
    }
    memory = row.get("fragmented_pressure_memory")
    if isinstance(memory, Mapping):
        context["fragmented_pressure_memory"] = dict(memory)
    if impact_tier:
        context["impact_tier"] = impact_tier
        context["impact_reasons"] = impact_reasons or []
        context["low_event_high_impact_candidate"] = bool(low_event_high_impact_candidate)
    return context


def _is_key_level_radar_exception(row: Mapping[str, Any], watch_payload: Mapping[str, Any]) -> bool:
    if _optional_bool(watch_payload.get("valid_for_execution")) is True:
        return False
    if _optional_bool(watch_payload.get("market_context_applied")) is not True:
        return False
    if _structure_invalid(watch_payload):
        return False
    price_position = str(watch_payload.get("price_position") or "").upper()
    if price_position not in _KEY_LEVEL_PRICE_POSITIONS:
        return False
    direction = _watch_direction(watch_payload) or _normalize_direction(row.get("direction"))
    if price_position == "MAIN_RESISTANCE" and direction != "SELL":
        return False
    if price_position == "MAIN_SUPPORT" and direction != "BUY":
        return False
    return _low_event_count(row)


def _is_watch_payload(payload: Mapping[str, Any] | None) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if _optional_bool(payload.get("valid_for_execution")) is True:
        return False
    status = str(payload.get("status") or "").upper()
    if status.endswith("_WATCH"):
        return True
    event = str(payload.get("event") or "").lower()
    return event == "signal_watch_json" and "WATCH" in status


def _key_level_exception_reasons(row: Mapping[str, Any], watch_payload: Mapping[str, Any]) -> list[str]:
    reasons = ["LOW_EVENT_COUNT", str(watch_payload.get("price_position") or "").upper(), "KEY_LEVEL_CONTEXT"]
    if _normalize_direction(row.get("direction")):
        reasons.append("PRESSURE_TIER3_RADAR")
    return reasons


def _low_event_count(row: Mapping[str, Any], max_events: int = 5) -> bool:
    metrics = row.get("metrics")
    if not isinstance(metrics, Mapping):
        return False
    scope = str(row.get("tier_scope") or LIVE_SCOPE).lower()
    metric_key = "live" if scope.startswith("live") else "session" if scope.startswith("session") else "archive"
    scoped_metrics = metrics.get(metric_key)
    if not isinstance(scoped_metrics, Mapping):
        scoped_metrics = metrics.get("live") if isinstance(metrics.get("live"), Mapping) else {}
    try:
        event_count = int(scoped_metrics.get("event_count") or 0)
    except (TypeError, ValueError):
        return False
    return 0 < event_count <= max_events


def _watch_direction(payload: Mapping[str, Any]) -> str | None:
    for key in ("watch_direction", "candidate_direction", "validated_direction", "final_direction", "raw_direction"):
        direction = _normalize_direction(payload.get(key))
        if direction:
            return direction
    return None


def _structure_invalid(payload: Mapping[str, Any]) -> bool:
    for key in ("structure_invalid", "structure_invalidated", "regime_invalidated"):
        if _optional_bool(payload.get(key)) is True:
            return True
    for key in ("direction_validation_status", "target_block_reason", "market_structure_status"):
        text = str(payload.get(key) or "").upper()
        if text in {"INVALID", "INVALIDATED", "STRUCTURE_INVALID", "MARKET_STRUCTURE_INVALID"}:
            return True
        if "CONFLICT" in text:
            return True
    market_structure = payload.get("market_structure")
    if isinstance(market_structure, Mapping):
        text = str(market_structure.get("status") or market_structure.get("structure_status") or "").upper()
        if text in {"INVALID", "INVALIDATED", "STRUCTURE_INVALID", "MARKET_STRUCTURE_INVALID"}:
            return True
    return False


def _scope_metrics(
    symbol: str,
    scope: str,
    *,
    events: Sequence[Any],
    blocks: Sequence[Any],
    now: datetime,
    clean_block_seconds: int,
    candidate_lifecycle: Mapping[str, Any] | None,
    theme_scores: Sequence[Mapping[str, Any]] | None,
) -> _ScopeMetrics:
    symbol_events = [event for event in events if _event_symbol(event) == symbol]
    symbol_blocks = [block for block in blocks if _block_symbol(block) == symbol]
    directions = Counter(
        direction for direction in (_event_direction(event) for event in symbol_events) if direction in {"BUY", "SELL"}
    )
    direction = _latest_direction(symbol_events) or _latest_block_direction(symbol_blocks)
    directional_total = sum(directions.values())
    direction_purity = (max(directions.values()) / directional_total) if directional_total else 0.0
    latest_event_age = _latest_event_age(symbol_events, now)
    clean_blocks = [block for block in symbol_blocks if _block_duration(block) >= clean_block_seconds]
    latest_clean_block = max(clean_blocks, key=_block_end, default=None)
    clean_block_duration = _block_duration(latest_clean_block) if latest_clean_block is not None else 0.0
    clean_block_age = None if latest_clean_block is None else _age_seconds(_block_end(latest_clean_block), now)
    clean_block_count = len(clean_blocks)
    max_clean_block_minutes = max((_block_duration(block) / 60.0 for block in clean_blocks), default=0.0)
    effective_density = max((_block_effective_density(block) for block in symbol_blocks), default=0.0)
    lifecycle_role = _lifecycle_role(symbol, candidate_lifecycle)
    theme_aligned = _theme_aligned(symbol, direction, theme_scores)
    event_count = len(symbol_events)
    effective_ticks = sum(_event_effective_ticks(event) for event in symbol_events)
    run_count = _symbol_run_count(events, symbol)
    same_symbol_reentry_count = max(0, run_count - 1)
    interrupted_by_other_symbols = same_symbol_reentry_count > 0
    fragmented_event_count = event_count if interrupted_by_other_symbols else 0
    pressure_memory_score = _pressure_memory_score(
        event_count=event_count,
        effective_ticks=effective_ticks,
        same_symbol_reentry_count=same_symbol_reentry_count,
        clean_block_count=clean_block_count,
    )
    score, reasons = _score_metrics(
        scope=scope,
        event_count=event_count,
        effective_ticks=effective_ticks,
        latest_event_age_seconds=latest_event_age,
        clean_block_duration_seconds=clean_block_duration,
        clean_block_age_seconds=clean_block_age,
        effective_density_per_minute=effective_density,
        direction_purity=direction_purity,
        lifecycle_role=lifecycle_role,
        theme_aligned=theme_aligned,
        clean_block_seconds=clean_block_seconds,
        pressure_memory_score=pressure_memory_score,
        same_symbol_reentry_count=same_symbol_reentry_count,
        clean_block_count=clean_block_count,
    )
    return _ScopeMetrics(
        symbol=symbol,
        scope=scope,
        event_count=event_count,
        effective_ticks=effective_ticks,
        latest_event_age_seconds=latest_event_age,
        clean_block_duration_seconds=clean_block_duration,
        clean_block_age_seconds=clean_block_age,
        effective_density_per_minute=effective_density,
        direction=direction,
        direction_purity=direction_purity,
        lifecycle_role=lifecycle_role,
        theme_aligned=theme_aligned,
        run_count=run_count,
        same_symbol_reentry_count=same_symbol_reentry_count,
        interrupted_by_other_symbols=interrupted_by_other_symbols,
        clean_block_count=clean_block_count,
        max_clean_block_minutes=max_clean_block_minutes,
        fragmented_event_count=fragmented_event_count,
        pressure_memory_score=pressure_memory_score,
        score=score,
        reasons=tuple(reasons),
    )


def _score_metrics(
    *,
    scope: str,
    event_count: int,
    effective_ticks: int,
    latest_event_age_seconds: float | None,
    clean_block_duration_seconds: float,
    clean_block_age_seconds: float | None,
    effective_density_per_minute: float,
    direction_purity: float,
    lifecycle_role: str | None,
    theme_aligned: bool,
    clean_block_seconds: int,
    pressure_memory_score: float,
    same_symbol_reentry_count: int,
    clean_block_count: int,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    if event_count > 0:
        score += min(16.0, event_count * 2.0)
        reasons.append(f"{scope}_PRESSURE_EVENTS")
    if effective_ticks > 0:
        score += min(18.0, effective_ticks * 1.5)
        reasons.append("EFFECTIVE_TICKS_PRESENT")
    if clean_block_duration_seconds >= clean_block_seconds:
        score += min(30.0, 22.0 + ((clean_block_duration_seconds - clean_block_seconds) / clean_block_seconds) * 8.0)
        if scope == LIVE_SCOPE:
            reasons.append("RECENT_CLEAN_BLOCK_GE_5M")
        elif scope == SESSION_SCOPE:
            reasons.append("SESSION_CLEAN_BLOCK_GE_5M")
        else:
            reasons.append("ARCHIVE_CLEAN_BLOCK_GE_5M")
    elif clean_block_duration_seconds > 0:
        score += min(8.0, (clean_block_duration_seconds / clean_block_seconds) * 8.0)
    if effective_density_per_minute > 0:
        score += min(10.0, effective_density_per_minute)
        reasons.append("PRESSURE_DENSITY_PRESENT")
    if direction_purity >= 0.75:
        score += 12.0
        reasons.append("DIRECTION_PURITY_HIGH")
    elif direction_purity > 0:
        score += direction_purity * 8.0
    if latest_event_age_seconds is not None:
        recency_window = 7200.0 if scope == LIVE_SCOPE else 86400.0 if scope == SESSION_SCOPE else 604800.0
        score += max(0.0, 8.0 * (1.0 - min(latest_event_age_seconds, recency_window) / recency_window))
        if clean_block_age_seconds is None or latest_event_age_seconds <= clean_block_age_seconds:
            reasons.append("LATEST_PRESSURE_ACTIVE")
    role_bonus = {
        "ACTIVE_CANDIDATE": 10.0,
        "LATEST_IGNITION_WATCH": 7.0,
        "PREVIOUS_MAJOR_LEADER": 5.0,
        "SECONDARY_CANDIDATE": 3.0,
        "HISTORICAL_LEADER": 2.0,
    }.get(lifecycle_role, 0.0)
    if role_bonus:
        score += role_bonus
        reasons.append(lifecycle_role or "")
    if theme_aligned:
        score += 6.0
        reasons.append("THEME_ALIGNED")
    if same_symbol_reentry_count >= 2:
        score += min(10.0, pressure_memory_score / 10.0)
        reasons.append("FRAGMENTED_PRESSURE_REPEATED")
        if clean_block_count == 0:
            reasons.append("NO_CLEAN_BLOCK_FRAGMENTED_MEMORY")
    if pressure_memory_score >= 60.0:
        reasons.append("PRESSURE_MEMORY_HIGH")
    if event_count == 0 and clean_block_duration_seconds == 0:
        reasons.append("NO_PRESSURE_IN_SCOPE")
    return min(100.0, score), reasons


def _tier_for_metrics(metrics: _ScopeMetrics) -> str:
    if metrics.event_count == 0 and metrics.clean_block_duration_seconds <= 0:
        return TIER_NONE
    clean_block_valid = metrics.clean_block_duration_seconds > 0
    if clean_block_valid and metrics.score >= 55.0:
        return TIER_1_PRIMARY_ANALYSIS
    if not clean_block_valid:
        if metrics.pressure_memory_score >= 60.0 or metrics.same_symbol_reentry_count >= 2:
            return TIER_PRESSURE_MEMORY_RADAR
        if metrics.theme_aligned:
            return TIER_THEME_ROTATION_RADAR
        if metrics.score >= 35.0:
            return TIER_FRAGMENTED_PRESSURE_RADAR
        return TIER_3_THEME_RADAR
    if metrics.score >= 35.0:
        return TIER_2_CONFIRMATION_SUPPORT
    return TIER_3_THEME_RADAR


def _effective_tier(
    live_tier: str,
    session_tier: str,
    archive_tier: str,
    live_metrics: _ScopeMetrics,
    session_metrics: _ScopeMetrics,
    archive_metrics: _ScopeMetrics,
) -> tuple[str, str, float, list[str]]:
    if live_tier != TIER_NONE:
        return live_tier, LIVE_SCOPE, live_metrics.score, list(live_metrics.reasons)
    if session_tier != TIER_NONE:
        tier = TIER_2_CONFIRMATION_SUPPORT if session_tier == TIER_1_PRIMARY_ANALYSIS else session_tier
        reasons = list(session_metrics.reasons)
        if session_tier == TIER_1_PRIMARY_ANALYSIS:
            reasons.append("SESSION_FALLBACK_CAPPED_BELOW_LIVE")
        return tier, SESSION_SCOPE, session_metrics.score, reasons
    if archive_tier != TIER_NONE:
        reasons = list(archive_metrics.reasons)
        reasons.extend(["NO_RECENT_CONFIRMATION", "STALE_PRESSURE"])
        return TIER_STALE_ARCHIVE, ARCHIVE_SCOPE, archive_metrics.score, reasons
    return TIER_NONE, NONE_SCOPE, 0.0, ["NO_PRESSURE_AVAILABLE"]


def _metrics_payload(metrics: _ScopeMetrics) -> dict[str, Any]:
    return {
        "event_count": metrics.event_count,
        "effective_ticks": metrics.effective_ticks,
        "latest_event_age_seconds": (
            None if metrics.latest_event_age_seconds is None else round(metrics.latest_event_age_seconds, 3)
        ),
        "clean_block_duration_seconds": round(metrics.clean_block_duration_seconds, 3),
        "clean_block_age_seconds": (
            None if metrics.clean_block_age_seconds is None else round(metrics.clean_block_age_seconds, 3)
        ),
        "effective_density_per_minute": round(metrics.effective_density_per_minute, 3),
        "direction": metrics.direction,
        "direction_purity": round(metrics.direction_purity, 3),
        "lifecycle_role": metrics.lifecycle_role,
        "theme_aligned": metrics.theme_aligned,
        "fragmented_event_count": metrics.fragmented_event_count,
        "clean_block_count": metrics.clean_block_count,
        "max_clean_block_minutes": round(metrics.max_clean_block_minutes, 3),
        "same_symbol_reentry_count": metrics.same_symbol_reentry_count,
        "run_count": metrics.run_count,
        "interrupted_by_other_symbols": metrics.interrupted_by_other_symbols,
        "pressure_memory_score": round(metrics.pressure_memory_score, 3),
        "score": round(metrics.score, 3),
        "reasons": list(metrics.reasons),
    }


def _tier_action(tier: str) -> str:
    if tier == TIER_1_PRIMARY_ANALYSIS:
        return "PRIORITIZE_ANALYSIS"
    if tier == TIER_2_CONFIRMATION_SUPPORT:
        return "CONFIRMATION_SUPPORT"
    if tier == TIER_PRESSURE_MEMORY_RADAR:
        return "PRESSURE_MEMORY_RADAR_ONLY"
    if tier == TIER_THEME_ROTATION_RADAR:
        return "THEME_ROTATION_RADAR_ONLY"
    if tier == TIER_FRAGMENTED_PRESSURE_RADAR:
        return "FRAGMENTED_PRESSURE_RADAR_ONLY"
    if tier == TIER_3_THEME_RADAR:
        return "RADAR_ONLY"
    if tier == TIER_STALE_ARCHIVE:
        return "AUDIT_ONLY"
    if tier == TIER_UNSAFE_MIXED_DEPLOYMENT:
        return "DO_NOT_RANK"
    return "NO_ACTION"


def _tier_family(tier: str) -> str:
    return {
        TIER_1_PRIMARY_ANALYSIS: "CLEAN_BLOCK",
        TIER_2_CONFIRMATION_SUPPORT: "CONFIRMATION_SUPPORT",
        TIER_PRESSURE_MEMORY_RADAR: "PRESSURE_MEMORY_RADAR",
        TIER_THEME_ROTATION_RADAR: "THEME_ROTATION_RADAR",
        TIER_FRAGMENTED_PRESSURE_RADAR: "FRAGMENTED_PRESSURE_RADAR",
        TIER_3_THEME_RADAR: "THEME_RADAR",
        TIER_STALE_ARCHIVE: "ARCHIVE",
        TIER_UNSAFE_MIXED_DEPLOYMENT: "UNSAFE_MIXED_DEPLOYMENT",
        TIER_NONE: "NONE",
    }.get(tier, "UNKNOWN")


def _symbol_row_sort_key(row: Mapping[str, Any]) -> tuple[int, float, str]:
    priority = {
        TIER_1_PRIMARY_ANALYSIS: 0,
        TIER_2_CONFIRMATION_SUPPORT: 1,
        TIER_PRESSURE_MEMORY_RADAR: 2,
        TIER_THEME_ROTATION_RADAR: 3,
        TIER_FRAGMENTED_PRESSURE_RADAR: 4,
        TIER_3_THEME_RADAR: 5,
        TIER_STALE_ARCHIVE: 6,
        TIER_UNSAFE_MIXED_DEPLOYMENT: 7,
        TIER_NONE: 8,
    }.get(str(row.get("effective_pressure_tier")), 9)
    return priority, -float(row.get("tier_score") or 0.0), str(row.get("symbol") or "")


def _all_symbols(
    events: Sequence[Any],
    *,
    symbol_activity: Mapping[str, Mapping[str, Any]] | None,
    clean_watch_candidates: Sequence[Mapping[str, Any]] | None,
    candidate_lifecycle: Mapping[str, Any] | None,
) -> list[str]:
    symbols = {_event_symbol(event) for event in events if _event_symbol(event)}
    symbols.update(str(symbol or "").upper() for symbol in symbol_activity or {})
    for candidate in clean_watch_candidates or []:
        symbol = str(candidate.get("symbol") or "").upper()
        if symbol:
            symbols.add(symbol)
    for key in (
        "active_candidate_symbol",
        "latest_meaningful_candidate_symbol",
        "latest_ignition_watch_symbol",
        "previous_major_leader_symbol",
        "secondary_candidate_symbol",
        "historical_leader_symbol",
    ):
        symbol = str((candidate_lifecycle or {}).get(key) or "").upper()
        if symbol:
            symbols.add(symbol)
    return sorted(symbols)


def _lifecycle_role(symbol: str, candidate_lifecycle: Mapping[str, Any] | None) -> str | None:
    lifecycle = candidate_lifecycle or {}
    if str(lifecycle.get("active_candidate_symbol") or "").upper() == symbol:
        return "ACTIVE_CANDIDATE"
    if str(lifecycle.get("latest_ignition_watch_symbol") or "").upper() == symbol:
        return "LATEST_IGNITION_WATCH"
    if str(lifecycle.get("previous_major_leader_symbol") or "").upper() == symbol:
        return "PREVIOUS_MAJOR_LEADER"
    if str(lifecycle.get("secondary_candidate_symbol") or "").upper() == symbol:
        return "SECONDARY_CANDIDATE"
    for leader in lifecycle.get("historical_leaders") or []:
        if isinstance(leader, Mapping) and str(leader.get("symbol") or "").upper() == symbol:
            return "HISTORICAL_LEADER"
    return None


def _theme_aligned(symbol: str, direction: str | None, theme_scores: Sequence[Mapping[str, Any]] | None) -> bool:
    if direction not in {"BUY", "SELL"}:
        return False
    base_quote = _split_symbol(symbol)
    if base_quote is None:
        return False
    base, quote = base_quote
    if direction == "BUY":
        expected = {f"{base}_STRENGTH", f"{quote}_WEAKNESS"}
    else:
        expected = {f"{base}_WEAKNESS", f"{quote}_STRENGTH"}
    themes = {str(theme.get("theme") or "").upper() for theme in theme_scores or [] if isinstance(theme, Mapping)}
    return bool(expected & themes)


def _split_symbol(symbol: str) -> tuple[str, str] | None:
    symbol = str(symbol or "").upper()
    if len(symbol) != 6:
        return None
    base = symbol[:3]
    quote = symbol[3:]
    if quote in _CURRENCIES and (base in _CURRENCIES or base in _METAL_BASES):
        return base, quote
    return None


def _event_symbol(event: Any) -> str:
    return str(getattr(event, "symbol", "") or "").upper()


def _block_symbol(block: Any) -> str:
    return str(getattr(block, "symbol", "") or "").upper()


def _event_timestamp(event: Any) -> datetime:
    return _coerce_timestamp(getattr(event, "timestamp", None))


def _block_end(block: Any) -> datetime:
    return _coerce_timestamp(getattr(block, "end", None))


def _block_duration(block: Any) -> float:
    if block is None:
        return 0.0
    return _safe_float(getattr(block, "duration_seconds", 0.0))


def _block_effective_density(block: Any) -> float:
    return _safe_float(
        getattr(block, "effective_density_per_minute", None)
        or getattr(block, "density_per_minute", None)
        or 0.0
    )


def _block_direction(block: Any) -> str | None:
    return _normalize_direction(getattr(block, "direction", None))


def _latest_block_direction(blocks: Sequence[Any]) -> str | None:
    for block in sorted(blocks, key=_block_end, reverse=True):
        direction = _block_direction(block)
        if direction:
            return direction
    return None


def _symbol_run_count(events: Sequence[Any], symbol: str) -> int:
    runs = 0
    previous_was_symbol = False
    for event in sorted(events, key=_event_timestamp):
        is_symbol = _event_symbol(event) == symbol
        if is_symbol and not previous_was_symbol:
            runs += 1
        previous_was_symbol = is_symbol
    return runs


def _pressure_memory_score(
    *,
    event_count: int,
    effective_ticks: int,
    same_symbol_reentry_count: int,
    clean_block_count: int,
) -> float:
    score = 0.0
    score += min(35.0, event_count * 1.0)
    score += min(25.0, effective_ticks * 0.35)
    score += min(30.0, same_symbol_reentry_count * 2.0)
    if same_symbol_reentry_count >= 2 and clean_block_count == 0:
        score += 10.0
    elif clean_block_count > 0:
        score += min(10.0, clean_block_count * 3.0)
    return min(100.0, score)


def _event_direction(event: Any) -> str | None:
    for attr in ("direction", "throttled_inferred_direction", "inherited_direction"):
        direction = _normalize_direction(getattr(event, attr, None))
        if direction:
            return direction
    return None


def _latest_direction(events: Sequence[Any]) -> str | None:
    for event in sorted(events, key=_event_timestamp, reverse=True):
        direction = _event_direction(event)
        if direction:
            return direction
    return None


def _event_effective_ticks(event: Any) -> int:
    ticks = getattr(event, "effective_ticks", 1)
    try:
        return max(1, int(ticks() if callable(ticks) else ticks))
    except (TypeError, ValueError):
        return 1


def _latest_event_age(events: Sequence[Any], now: datetime) -> float | None:
    if not events:
        return None
    return _age_seconds(max((_event_timestamp(event) for event in events), default=now), now)


def _age_seconds(timestamp: datetime, now: datetime) -> float:
    return max(0.0, (now - timestamp).total_seconds())


def _coerce_timestamp(value: Any) -> datetime:
    if not isinstance(value, datetime):
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalize_direction(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if text in {"BUY", "SELL"}:
        return text
    return None


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_float(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0
