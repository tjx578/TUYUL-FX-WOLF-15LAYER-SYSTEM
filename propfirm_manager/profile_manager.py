"""
Prop Firm Profile Manager

Loads and caches prop firm profiles, dynamically imports guard classes.
"""

import importlib
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from propfirm_manager.profiles.base_guard import BasePropFirmGuard, GuardResult


class PropFirmManager:
    """Manages prop firm profile loading and guard execution."""

    _profile_cache: dict[str, "PropFirmManager"] = {}

    def __new__(cls, profile_name: str):
        if profile_name not in cls._profile_cache:
            instance = super().__new__(cls)
            cls._profile_cache[profile_name] = instance
        return cls._profile_cache[profile_name]

    def __init__(self, profile_name: str):
        if hasattr(self, "profile_name"):
            return
        self.profile_name = profile_name
        self._load_profile()
        self._load_guard()

    def _load_profile(self) -> None:
        base_dir = Path(__file__).parent / "profiles" / self.profile_name
        profile_path = base_dir / "profile.yaml"
        if not profile_path.exists():
            raise FileNotFoundError(f"Profile not found: {profile_path}")
        with open(profile_path) as f:
            config = yaml.safe_load(f)
        self.rules = config.get("rules", {})
        self.features = config.get("features", {})
        self.version = config.get("version", "unknown")
        logger.info(f"Loaded prop firm profile: {self.profile_name} v{self.version}")

    def _load_guard(self) -> None:
        module_path = f"propfirm_manager.profiles.{self.profile_name}.guard"
        try:
            module = importlib.import_module(module_path)
        except ImportError as e:
            raise ImportError(f"Failed to import guard for {self.profile_name}: {e}") from e
        class_name = self._profile_to_class_name(self.profile_name)
        guard_class = getattr(module, class_name, None)
        if guard_class is None:
            raise ImportError(f"Guard class {class_name} not found in {module_path}")
        self.guard: BasePropFirmGuard = guard_class(self.rules)

    def _profile_to_class_name(self, profile_name: str) -> str:
        parts = profile_name.split("_")
        return "".join(p.upper() if len(p) <= 4 else p.capitalize() for p in parts) + "Guard"

    @classmethod
    def for_account(cls, account_id: str) -> "PropFirmManager":
        """Factory method: create manager based on account registry."""
        registry_path = Path(__file__).parent / "account_registry.yaml"
        if not registry_path.exists():
            raise FileNotFoundError(f"Account registry not found: {registry_path}")
        with open(registry_path) as f:
            registry = yaml.safe_load(f)
        profile_name = registry.get(account_id)
        if profile_name is None:
            raise ValueError(f"Account {account_id} not in registry")
        if profile_name not in cls._profile_cache:
            cls._profile_cache[profile_name] = cls(profile_name)
        return cls._profile_cache[profile_name]

    def evaluate_trade(
        self,
        account_state: dict[str, Any],
        trade_risk: dict[str, Any],
    ) -> GuardResult:
        """Evaluate if trade is allowed under prop firm rules."""
        return self.guard.check(account_state, trade_risk)

    def get_rules(self) -> dict[str, Any]:
        """Get prop firm rules."""
        return self.rules.copy()

    def get_features(self) -> dict[str, Any]:
        """Get prop firm features."""
        return self.features.copy()
