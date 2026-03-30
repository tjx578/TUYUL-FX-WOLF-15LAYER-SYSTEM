"""
Feature Flags — ARCH-GAP-10
==============================
Redis-backed per-service feature flags with percentage-based rollout.

Enables operators to:
  - Toggle features per service without redeploying
  - Gradually roll out new features (0–100% rollout)
  - Set maintenance mode per service
  - Query flag state from any service

All flag state is persisted in Redis HASHes so it survives restarts and
is visible across all services instantly.

Redis layout::

    wolf15:feature_flags:{service}   HASH  { flag_name → JSON payload }

Each flag payload::

    {
        "enabled": bool,
        "rollout_pct": int (0-100),
        "reason": str,
        "changed_by": str,
        "updated_at": ISO timestamp
    }

Zone: infrastructure/ — shared utility, no business logic.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from loguru import logger


@dataclass(frozen=True, slots=True)
class FlagState:
    """Immutable snapshot of a single feature flag."""

    name: str
    enabled: bool = False
    rollout_pct: int = 100
    reason: str = ""
    changed_by: str = "system"
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Well-known service names ──────────────────────────────────────────────────
KNOWN_SERVICES = frozenset({"api", "engine", "ingest", "orchestrator", "trade", "worker"})

# ── Well-known flag names ─────────────────────────────────────────────────────
FLAG_MAINTENANCE_MODE = "maintenance_mode"
FLAG_ACCEPT_SIGNALS = "accept_signals"
FLAG_ACCEPT_TRADES = "accept_trades"
FLAG_ENABLE_FIREWALL = "enable_firewall"
FLAG_ENABLE_NEWS_LOCK = "enable_news_lock"


class FeatureFlagService:
    """Redis-backed feature flag manager for per-service toggles.

    Parameters
    ----------
    redis_client:
        Sync Redis client (``storage.redis_client.RedisClient`` compatible).
        Must support ``.hget()``, ``.hset()``, ``.hgetall()``, ``.hdel()``.
    key_prefix:
        Redis key prefix. Defaults to ``wolf15:feature_flags``.
    """

    def __init__(
        self,
        redis_client: Any,
        key_prefix: str = "wolf15:feature_flags",
    ) -> None:
        self._redis = redis_client
        self._prefix = key_prefix

    # ── Key helpers ───────────────────────────────────────────────────────────

    def _key(self, service: str) -> str:
        return f"{self._prefix}:{service}"

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_flag(self, service: str, flag_name: str) -> FlagState | None:
        """Get a single flag for a service. Returns None if not set."""
        raw = self._redis.hget(self._key(service), flag_name)
        if raw is None:
            return None
        return self._decode(flag_name, raw)

    def get_all_flags(self, service: str) -> dict[str, FlagState]:
        """Get all flags for a service."""
        raw_map = self._redis.hgetall(self._key(service))
        if not raw_map:
            return {}
        result: dict[str, FlagState] = {}
        for name, raw in raw_map.items():
            fname = name if isinstance(name, str) else name.decode()
            result[fname] = self._decode(fname, raw)
        return result

    def get_all_services(self) -> dict[str, dict[str, FlagState]]:
        """Get flags for all known services."""
        return {svc: self.get_all_flags(svc) for svc in KNOWN_SERVICES}

    # ── Write ─────────────────────────────────────────────────────────────────

    def set_flag(
        self,
        service: str,
        flag_name: str,
        *,
        enabled: bool,
        rollout_pct: int = 100,
        reason: str = "",
        changed_by: str = "operator",
    ) -> FlagState:
        """Create or update a feature flag for a service."""
        if rollout_pct < 0 or rollout_pct > 100:
            raise ValueError(f"rollout_pct must be 0-100, got {rollout_pct}")

        state = FlagState(
            name=flag_name,
            enabled=enabled,
            rollout_pct=rollout_pct,
            reason=reason,
            changed_by=changed_by,
            updated_at=datetime.now(UTC).isoformat(),
        )
        payload = json.dumps(state.to_dict())
        self._redis.hset(self._key(service), flag_name, payload)
        logger.info(
            "[FeatureFlags] {}/{} → enabled={} rollout={}% by={} reason={}",
            service,
            flag_name,
            enabled,
            rollout_pct,
            changed_by,
            reason,
        )
        return state

    def delete_flag(self, service: str, flag_name: str) -> bool:
        """Remove a flag entirely. Returns True if it existed."""
        result = self._redis.hdel(self._key(service), flag_name)
        return bool(result)

    # ── Evaluation ────────────────────────────────────────────────────────────

    def is_enabled(
        self,
        service: str,
        flag_name: str,
        *,
        context_key: str = "",
        default: bool = True,
    ) -> bool:
        """Check if a feature is enabled for a given service.

        Parameters
        ----------
        service:
            Service name (e.g. "engine").
        flag_name:
            Feature flag name (e.g. "accept_signals").
        context_key:
            Optional key for percentage-based rollout (e.g. account_id or
            symbol). Hashed to determine if this context falls within
            the rollout percentage.
        default:
            Value to return when the flag is not set. Defaults to True
            (fail-open for unset flags).
        """
        state = self.get_flag(service, flag_name)
        if state is None:
            return default

        if not state.enabled:
            return False

        if state.rollout_pct >= 100:
            return True
        if state.rollout_pct <= 0:
            return False

        # Deterministic hash-based rollout
        hash_input = f"{service}:{flag_name}:{context_key}"
        bucket = int(hashlib.sha256(hash_input.encode()).hexdigest()[:8], 16) % 100
        return bucket < state.rollout_pct

    def is_maintenance(self, service: str) -> bool:
        """Check if a service is in maintenance mode."""
        return self.is_enabled(service, FLAG_MAINTENANCE_MODE, default=False)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _decode(flag_name: str, raw: str | bytes) -> FlagState:
        data = raw if isinstance(raw, str) else raw.decode()
        parsed = json.loads(data)
        return FlagState(
            name=flag_name,
            enabled=parsed.get("enabled", False),
            rollout_pct=parsed.get("rollout_pct", 100),
            reason=parsed.get("reason", ""),
            changed_by=parsed.get("changed_by", ""),
            updated_at=parsed.get("updated_at", ""),
        )
