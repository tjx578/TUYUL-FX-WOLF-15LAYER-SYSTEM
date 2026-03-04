from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from config_loader import CONFIG


@dataclass(frozen=True)
class ConfigProfileState:
    active_profile: str
    locked: bool = False


@dataclass(frozen=True)
class ConfigRevision:
    revision_id: int
    timestamp: str
    actor: str
    reason: str
    action: str
    diff: dict[str, Any]


class ConfigProfileEngine:
    """Runtime config profile selector with deterministic override merge."""

    _instance: "ConfigProfileEngine | None" = None
    _lock = Lock()

    def __new__(cls) -> "ConfigProfileEngine":
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
                    cls._instance._rw_lock = Lock()
                    cls._instance._profiles = cls._instance._build_profiles()
                    cls._instance._scoped_overrides = {
                        "global": {},
                        "account": {},
                        "prop_firm": {},
                        "pair": {},
                    }
                    cls._instance._state = ConfigProfileState(active_profile="default")
                    cls._instance._revisions: list[ConfigRevision] = []
                    cls._instance._revision_seq = 0
        return cls._instance

    def _build_profiles(self) -> dict[str, dict[str, Any]]:
        base = {
            "default": {},
            "conservative": {
                "risk": {"position_sizing": {"default_risk_percent": 0.005}},
            },
            "aggressive": {
                "risk": {"position_sizing": {"default_risk_percent": 0.015}},
            },
        }

        yaml_profiles = CONFIG.get("settings", {}).get("profiles", {})
        if isinstance(yaml_profiles, dict):
            for name, override in yaml_profiles.items():
                if isinstance(override, dict):
                    base[str(name)] = override
        return base

    def list_profiles(self) -> list[str]:
        return sorted(self._profiles.keys())

    def list_scoped_overrides(self) -> dict[str, list[str]]:
        return {
            scope: sorted(items.keys())
            for scope, items in self._scoped_overrides.items()
        }

    def list_revisions(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        selected = self._revisions[-limit:]
        return [
            {
                "revision_id": rev.revision_id,
                "timestamp": rev.timestamp,
                "actor": rev.actor,
                "reason": rev.reason,
                "action": rev.action,
                "diff": deepcopy(rev.diff),
            }
            for rev in selected
        ]

    def get_active_profile(self) -> str:
        return self._state.active_profile

    def is_locked(self) -> bool:
        return self._state.locked

    def activate(self, profile_name: str, actor: str = "system", reason: str = "CONFIG_ACTIVATE") -> dict[str, Any]:
        profile_name = profile_name.strip().lower()
        if profile_name not in self._profiles:
            raise ValueError(f"Unknown profile: {profile_name}")
        if self._state.locked:
            raise ValueError("Config is locked")

        with self._rw_lock:
            before_profile = self._state.active_profile
            self._state = ConfigProfileState(active_profile=profile_name, locked=self._state.locked)
            self._append_revision(
                actor=actor,
                reason=reason,
                action="ACTIVATE_PROFILE",
                before={"active_profile": before_profile},
                after={"active_profile": self._state.active_profile},
            )
        return {
            "active_profile": self._state.active_profile,
            "effective_config": self.get_effective_config(),
        }

    def set_lock(self, locked: bool, actor: str = "system", reason: str = "CONFIG_LOCK_TOGGLE") -> dict[str, Any]:
        with self._rw_lock:
            before_locked = self._state.locked
            self._state = ConfigProfileState(active_profile=self._state.active_profile, locked=locked)
            self._append_revision(
                actor=actor,
                reason=reason,
                action="SET_LOCK",
                before={"locked": before_locked},
                after={"locked": self._state.locked},
            )
        return {
            "active_profile": self._state.active_profile,
            "locked": self._state.locked,
        }

    def upsert_override(
        self,
        scope: str,
        key: str,
        override: dict[str, Any],
        actor: str = "system",
        reason: str = "UPSERT_OVERRIDE",
    ) -> dict[str, Any]:
        scope_norm = scope.strip().lower()
        if scope_norm not in self._scoped_overrides:
            raise ValueError(f"Unknown scope: {scope}")
        if self._state.locked:
            raise ValueError("Config is locked")
        scope_key = key.strip().upper()
        if not scope_key:
            raise ValueError("Scope key is required")

        with self._rw_lock:
            before = deepcopy(self._scoped_overrides[scope_norm].get(scope_key, {}))
            self._scoped_overrides[scope_norm][scope_key] = deepcopy(override)
            after = deepcopy(self._scoped_overrides[scope_norm][scope_key])
            self._append_revision(
                actor=actor,
                reason=reason,
                action="UPSERT_OVERRIDE",
                before={"scope": scope_norm, "key": scope_key, "override": before},
                after={"scope": scope_norm, "key": scope_key, "override": after},
            )

        return {
            "scope": scope_norm,
            "key": scope_key,
            "override": deepcopy(self._scoped_overrides[scope_norm][scope_key]),
        }

    def delete_override(self, scope: str, key: str, actor: str = "system", reason: str = "DELETE_OVERRIDE") -> dict[str, Any]:
        scope_norm = scope.strip().lower()
        if scope_norm not in self._scoped_overrides:
            raise ValueError(f"Unknown scope: {scope}")
        if self._state.locked:
            raise ValueError("Config is locked")

        scope_key = key.strip().upper()
        removed = None
        with self._rw_lock:
            removed = self._scoped_overrides[scope_norm].pop(scope_key, None)
            self._append_revision(
                actor=actor,
                reason=reason,
                action="DELETE_OVERRIDE",
                before={"scope": scope_norm, "key": scope_key, "override": deepcopy(removed or {})},
                after={"scope": scope_norm, "key": scope_key, "override": {}},
            )
        return {
            "deleted": bool(removed is not None),
            "scope": scope_norm,
            "key": scope_key,
        }

    def _append_revision(
        self,
        actor: str,
        reason: str,
        action: str,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> None:
        self._revision_seq += 1
        revision = ConfigRevision(
            revision_id=self._revision_seq,
            timestamp=datetime.now(UTC).isoformat(),
            actor=actor,
            reason=reason,
            action=action,
            diff=_dict_diff(before, after),
        )
        self._revisions.append(revision)

    def get_effective_config(
        self,
        account_id: str | None = None,
        prop_firm: str | None = None,
        pair: str | None = None,
    ) -> dict[str, Any]:
        merged = deepcopy(CONFIG)
        override = deepcopy(self._profiles.get(self._state.active_profile, {}))
        merged = _deep_merge(merged, override)

        global_override = deepcopy(self._scoped_overrides["global"].get("DEFAULT", {}))
        merged = _deep_merge(merged, global_override)

        if account_id:
            merged = _deep_merge(
                merged,
                deepcopy(self._scoped_overrides["account"].get(account_id.strip().upper(), {})),
            )
        if prop_firm:
            merged = _deep_merge(
                merged,
                deepcopy(self._scoped_overrides["prop_firm"].get(prop_firm.strip().upper(), {})),
            )
        if pair:
            merged = _deep_merge(
                merged,
                deepcopy(self._scoped_overrides["pair"].get(pair.strip().upper(), {})),
            )

        return merged


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_merge(dict(base[key]), value)
        else:
            base[key] = value
    return base


def _dict_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    diff: dict[str, Any] = {}
    keys = set(before.keys()) | set(after.keys())

    for key in keys:
        b_val = before.get(key)
        a_val = after.get(key)
        if isinstance(b_val, dict) and isinstance(a_val, dict):
            nested = _dict_diff(b_val, a_val)
            if nested:
                diff[key] = nested
            continue
        if b_val != a_val:
            diff[key] = {"before": deepcopy(b_val), "after": deepcopy(a_val)}

    return diff
