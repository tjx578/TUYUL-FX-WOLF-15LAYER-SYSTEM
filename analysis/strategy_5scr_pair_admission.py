"""Build pair-admission grants exclusively from the global raw ledger."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from contracts.strategy_5scr_pair_admission import PAIR_ADMISSION_RULE_VERSION, PairAdmissionGrant

DEFAULT_PAIR_ADMISSION_MIN_DURATION_SECONDS = 300.0
DEFAULT_PAIR_ADMISSION_MIN_EFFECTIVE_TICKS = 3
DEFAULT_PAIR_ADMISSION_TTL_SECONDS = 900


@dataclass(frozen=True)
class PairAdmissionAudit:
    """Shadow-safe grant/rejection accounting for rollout comparison."""

    grants: tuple[PairAdmissionGrant, ...]
    evaluated_blocks: int
    rejection_counts: dict[str, int]
    evaluations: tuple[dict[str, Any], ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "rule_version": PAIR_ADMISSION_RULE_VERSION,
            "evaluated_blocks": self.evaluated_blocks,
            "granted_blocks": len(self.grants),
            "rejected_blocks": self.evaluated_blocks - len(self.grants),
            "grant_rate": round(len(self.grants) / self.evaluated_blocks, 6)
            if self.evaluated_blocks
            else 0.0,
            "rejection_counts": dict(sorted(self.rejection_counts.items())),
            "evaluations": list(self.evaluations),
            "execution_authority": False,
        }


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        resolved = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip().replace("Z", "+00:00")
        try:
            resolved = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None
    if resolved.tzinfo is None or resolved.utcoffset() is None:
        return None
    return resolved.astimezone(UTC)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _raw_event_id(event: Any) -> str:
    identity = {
        "timestamp": _utc(_value(event, "timestamp")),
        "symbol": str(_value(event, "symbol") or "").upper(),
        "event_type": _value(event, "event_type"),
        "verdict": _value(event, "verdict"),
        "direction": _value(event, "direction"),
        "suppressed": _value(event, "suppressed", 0),
        "scanner_cycle_id": _value(event, "scanner_cycle_id"),
        "deployment_id": _value(event, "deployment_id"),
    }
    return "sha256:" + hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()


def _event_direction(event: Any) -> str | None:
    direction = str(_value(event, "direction") or "").strip().upper()
    if direction in {"BUY", "SELL"}:
        return direction
    verdict = str(_value(event, "verdict") or "").strip().upper()
    if verdict.endswith("_BUY"):
        return "BUY"
    if verdict.endswith("_SELL"):
        return "SELL"
    return None


def build_pair_admission_grant(
    block: Any,
    *,
    raw_events: Iterable[Any],
    source_clean_block_id: str | None = None,
    min_duration_seconds: float = DEFAULT_PAIR_ADMISSION_MIN_DURATION_SECONDS,
    min_effective_ticks: int = DEFAULT_PAIR_ADMISSION_MIN_EFFECTIVE_TICKS,
    ttl_seconds: int = DEFAULT_PAIR_ADMISSION_TTL_SECONDS,
) -> PairAdmissionGrant | None:
    """Return a grant only when raw-ledger evidence meets every authority rule."""

    symbol = str(_value(block, "symbol") or "").strip().upper()
    direction = str(_value(block, "direction") or "").strip().upper()
    start = _utc(_value(block, "start"))
    end = _utc(_value(block, "end"))
    duration = float(_value(block, "duration_seconds", 0.0) or 0.0)
    effective_ticks = int(_value(block, "effective_ticks", 0) or _value(block, "events", 0) or 0)
    if (
        not symbol
        or direction not in {"BUY", "SELL"}
        or start is None
        or end is None
        or end < start
        or duration < min_duration_seconds
        or effective_ticks < min_effective_ticks
    ):
        return None

    episode_evidence = [
        event
        for event in raw_events
        if str(_value(event, "symbol") or "").upper() == symbol
        and (timestamp := _utc(_value(event, "timestamp"))) is not None
        and start <= timestamp <= end
    ]
    if not episode_evidence:
        return None
    if any(_event_direction(event) != direction for event in episode_evidence):
        return None
    evidence = episode_evidence

    deployments = {
        str(_value(event, "deployment_id") or "").strip()
        for event in evidence
        if str(_value(event, "deployment_id") or "").strip()
    }
    if len(deployments) != 1:
        # Deployment mixing cannot produce authority.  The ledger may still be
        # retained for diagnostics, but admission fails closed.
        return None
    deployment_id = next(iter(deployments))

    source_event_ids = tuple(sorted({_raw_event_id(event) for event in evidence}))
    ledger_hash = "sha256:" + hashlib.sha256("|".join(source_event_ids).encode("utf-8")).hexdigest()
    identity = {
        "deployment_id": deployment_id,
        "symbol": symbol,
        "direction": direction,
        "episode_started_at_utc": start.isoformat(),
        "episode_observed_through_utc": end.isoformat(),
        "source_ledger_hash": ledger_hash,
        "rule_version": PAIR_ADMISSION_RULE_VERSION,
    }
    admission_id = "5scr-admission:" + hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()[:32]
    clean_ids = (source_clean_block_id,) if source_clean_block_id else ()
    return PairAdmissionGrant(
        pair_admission_id=admission_id,
        deployment_id=deployment_id,
        symbol=symbol,
        direction=direction,  # type: ignore[arg-type]
        episode_started_at_utc=start,
        episode_observed_through_utc=end,
        granted_at_utc=end,
        expires_at_utc=end + timedelta(seconds=max(1, ttl_seconds)),
        duration_seconds=duration,
        effective_ticks=effective_ticks,
        source_ledger_event_ids=source_event_ids,
        source_ledger_hash=ledger_hash,
        source_clean_block_ids=clean_ids,
    )


def _rejection_reason(
    block: Any,
    *,
    raw_events: tuple[Any, ...],
    min_duration_seconds: float,
    min_effective_ticks: int,
) -> str:
    symbol = str(_value(block, "symbol") or "").strip().upper()
    direction = str(_value(block, "direction") or "").strip().upper()
    start = _utc(_value(block, "start"))
    end = _utc(_value(block, "end"))
    duration = float(_value(block, "duration_seconds", 0.0) or 0.0)
    effective_ticks = int(_value(block, "effective_ticks", 0) or _value(block, "events", 0) or 0)
    if not symbol:
        return "SYMBOL_MISSING"
    if direction not in {"BUY", "SELL"}:
        return "DIRECTION_UNRESOLVED"
    if start is None or end is None or end < start:
        return "EPISODE_INTERVAL_INVALID"
    if duration < min_duration_seconds:
        return "DURATION_BELOW_MINIMUM"
    if effective_ticks < min_effective_ticks:
        return "EFFECTIVE_TICKS_BELOW_MINIMUM"
    evidence = [
        event
        for event in raw_events
        if str(_value(event, "symbol") or "").upper() == symbol
        and (timestamp := _utc(_value(event, "timestamp"))) is not None
        and start <= timestamp <= end
    ]
    if not evidence:
        return "RAW_LEDGER_EVIDENCE_MISSING"
    if any(_event_direction(event) is None for event in evidence):
        return "RAW_LEDGER_DIRECTION_UNRESOLVED"
    if any(_event_direction(event) != direction for event in evidence):
        return "RAW_LEDGER_DIRECTION_CONFLICT"
    deployments = {
        str(_value(event, "deployment_id") or "").strip()
        for event in evidence
        if str(_value(event, "deployment_id") or "").strip()
    }
    if not deployments:
        return "DEPLOYMENT_ID_MISSING"
    if len(deployments) > 1:
        return "MIXED_DEPLOYMENTS"
    return "PAIR_ADMISSION_CONTRACT_REJECTED"


def build_pair_admission_audit(
    blocks: Iterable[Any],
    *,
    raw_events: Iterable[Any],
    clean_block_ids: dict[tuple[str, str, str], str] | None = None,
    min_duration_seconds: float = DEFAULT_PAIR_ADMISSION_MIN_DURATION_SECONDS,
    min_effective_ticks: int = DEFAULT_PAIR_ADMISSION_MIN_EFFECTIVE_TICKS,
) -> PairAdmissionAudit:
    """Evaluate all blocks and retain explicit rejection reasons for shadow rollout."""

    events = tuple(raw_events)
    ids = clean_block_ids or {}
    grants: list[PairAdmissionGrant] = []
    evaluations: list[dict[str, Any]] = []
    rejection_counts: dict[str, int] = {}
    block_list = tuple(blocks)
    for block in block_list:
        start = _utc(_value(block, "start"))
        end = _utc(_value(block, "end"))
        symbol = str(_value(block, "symbol") or "").upper()
        key = (
            symbol,
            "" if start is None else start.isoformat(),
            "" if end is None else end.isoformat(),
        )
        grant = build_pair_admission_grant(
            block,
            raw_events=events,
            source_clean_block_id=ids.get(key),
            min_duration_seconds=min_duration_seconds,
            min_effective_ticks=min_effective_ticks,
        )
        if grant is not None:
            grants.append(grant)
            evaluations.append(
                {
                    "symbol": symbol,
                    "direction": str(_value(block, "direction") or "").upper(),
                    "episode_started_at_utc": None if start is None else start.isoformat(),
                    "episode_observed_through_utc": None if end is None else end.isoformat(),
                    "decision": "GRANTED",
                    "pair_admission_id": grant.pair_admission_id,
                    "rejection_reason": None,
                }
            )
            continue
        reason = _rejection_reason(
            block,
            raw_events=events,
            min_duration_seconds=min_duration_seconds,
            min_effective_ticks=min_effective_ticks,
        )
        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
        evaluations.append(
            {
                "symbol": symbol or None,
                "direction": str(_value(block, "direction") or "").upper() or None,
                "episode_started_at_utc": None if start is None else start.isoformat(),
                "episode_observed_through_utc": None if end is None else end.isoformat(),
                "decision": "REJECTED",
                "pair_admission_id": None,
                "rejection_reason": reason,
            }
        )
    ordered_grants = tuple(sorted(grants, key=lambda item: (item.granted_at_utc, item.symbol, item.pair_admission_id)))
    return PairAdmissionAudit(
        grants=ordered_grants,
        evaluated_blocks=len(block_list),
        rejection_counts=rejection_counts,
        evaluations=tuple(evaluations),
    )


def build_pair_admission_grants(
    blocks: Iterable[Any],
    *,
    raw_events: Iterable[Any],
    clean_block_ids: dict[tuple[str, str, str], str] | None = None,
    min_duration_seconds: float = DEFAULT_PAIR_ADMISSION_MIN_DURATION_SECONDS,
) -> tuple[PairAdmissionGrant, ...]:
    """Build deterministic grants for all eligible blocks in one global ledger."""

    return build_pair_admission_audit(
        blocks,
        raw_events=raw_events,
        clean_block_ids=clean_block_ids,
        min_duration_seconds=min_duration_seconds,
    ).grants


__all__ = [
    "DEFAULT_PAIR_ADMISSION_MIN_DURATION_SECONDS",
    "DEFAULT_PAIR_ADMISSION_MIN_EFFECTIVE_TICKS",
    "DEFAULT_PAIR_ADMISSION_TTL_SECONDS",
    "PairAdmissionAudit",
    "build_pair_admission_audit",
    "build_pair_admission_grant",
    "build_pair_admission_grants",
]
