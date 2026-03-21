"""
Prop Firm Profile Manager

Loads and caches prop firm profiles, dynamically imports guard classes.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from loguru import logger

from propfirm_manager.profiles.base_guard import (
    BasePropFirmGuard,
    GuardResult,
)

if TYPE_CHECKING:
    from propfirm_manager.resolved_rules import ResolvedPropRules


class PropFirmManager:
    """
    Manages prop firm profile loading and guard execution.

    Responsibilities:
        - Load profile YAML configuration (v1 and v2 formats)
        - Dynamically import guard class
        - Cache profiles to avoid repeated loads
        - Provide factory method for account-based lookup
    """

    # Class-level profile cache
    _profile_cache: dict[str, PropFirmManager] = {}

    def __new__(cls, profile_name: str):
        """
        Factory pattern to return cached instance if exists.

        Args:
            profile_name: Name of the profile

        Returns:
            PropFirmManager instance (cached or new)
        """
        if profile_name not in cls._profile_cache:
            instance = super().__new__(cls)
            cls._profile_cache[profile_name] = instance
        return cls._profile_cache[profile_name]

    def __init__(self, profile_name: str):
        """
        Initialize manager for a specific profile.

        Args:
            profile_name: Name of the profile (ftmo, aqua_instant_pro, etc.)

        Raises:
            FileNotFoundError: If profile files don't exist
            ImportError: If guard class can't be imported
        """
        # Skip re-initialization if already initialized
        if hasattr(self, "profile_name"):
            return

        self.profile_name = profile_name
        self._load_profile()
        self._load_guard()

    def _load_profile(self) -> None:
        """Load profile YAML configuration (v1 and v2 compatible)."""
        base_dir = Path(__file__).parent / "profiles" / self.profile_name
        profile_path = base_dir / "profile.yaml"

        if not profile_path.exists():
            raise FileNotFoundError(f"Profile not found: {profile_path}")

        with open(profile_path) as f:
            config = yaml.safe_load(f)

        self._raw_config: dict[str, Any] = config
        self.version = config.get("version", "unknown")
        self.features: dict[str, Any] = config.get("features", {})

        # Support both v1 ("rules" key) and v2 ("default_rules" key)
        if "rules" in config:
            self.rules: dict[str, Any] = config["rules"]
        elif "default_rules" in config:
            self.rules = dict(config["default_rules"])
        else:
            self.rules = {}

        logger.info(f"Loaded profile: {self.profile_name} v{self.version}")

    def _load_guard(self) -> None:
        """Dynamically import and instantiate guard class."""
        # Import the guard module
        module_path = f"propfirm_manager.profiles.{self.profile_name}.guard"
        try:
            module = importlib.import_module(module_path)
        except ImportError as e:
            raise ImportError(f"Failed to import guard for {self.profile_name}: {e}") from e

        # Get guard class name (e.g., FTMOGuard, AquaInstantProGuard)
        # Convert profile_name to class name format
        class_name = self._profile_to_class_name(self.profile_name)

        guard_class = getattr(module, class_name, None)
        if guard_class is None:
            raise ImportError(f"Guard class {class_name} not found in {module_path}")

        # Instantiate guard with flat rules (normalized from v1 or v2)
        self.guard: BasePropFirmGuard = guard_class(self.rules)
        logger.debug(f"Guard loaded: {class_name}")

    def _profile_to_class_name(self, profile_name: str) -> str:
        """
        Convert profile name to guard class name.

        Examples:
            ftmo -> FTMOGuard
            aqua_instant_pro -> AquaInstantProGuard

        Args:
            profile_name: Profile directory name

        Returns:
            Guard class name
        """
        # Special cases for all-caps acronyms
        if profile_name == "ftmo":
            return "FTMOGuard"

        # Split by underscore, capitalize each part, join, add "Guard"
        parts = profile_name.split("_")
        class_name = "".join(part.capitalize() for part in parts)
        return f"{class_name}Guard"

    @classmethod
    def for_account(cls, account_id: str) -> PropFirmManager:
        """
        Factory method: create manager based on account registry.

        Args:
            account_id: Account identifier (e.g., ACC-001)

        Returns:
            PropFirmManager instance for account's prop firm

        Raises:
            FileNotFoundError: If registry or profile not found
        """
        # Load account registry
        registry_path = (
            Path(__file__).parent / "account_registry.yaml"
        )

        if not registry_path.exists():
            raise FileNotFoundError(f"Account registry not found: {registry_path}")

        with open(registry_path) as f:
            registry = yaml.safe_load(f)

        profile_name = registry.get(account_id)
        if profile_name is None:
            raise ValueError(f"Account {account_id} not in registry")

        # Use cached instance if available
        if profile_name not in cls._profile_cache:
            cls._profile_cache[profile_name] = cls(profile_name)

        return cls._profile_cache[profile_name]

    def resolve_rules(self, plan_code: str, phase: str) -> ResolvedPropRules:
        """
        Resolve fully merged rules for a specific plan and phase.

        For v2 profiles this merges default_rules with the plan+phase overrides.
        For v1 profiles the flat rules are returned as-is under a synthetic plan.

        Args:
            plan_code: Plan identifier (e.g. "pro_100k", "challenge_100k").
            phase: Trading phase (e.g. "funded", "challenge", "verification").

        Returns:
            ResolvedPropRules instance (frozen, immutable).
        """
        from propfirm_manager.rule_resolver import PropFirmRuleResolver

        resolver = PropFirmRuleResolver()
        return resolver.resolve(self.profile_name, plan_code, phase)

    def evaluate_trade(
        self,
        account_state: dict[str, Any],
        trade_risk: dict[str, Any],
    ) -> GuardResult:
        """
        Evaluate if trade is allowed under prop firm rules.

        Args:
            account_state: Current account state
            trade_risk: Proposed trade risk parameters

        Returns:
            GuardResult (allowed/denied with details)
        """
        return self.guard.check(account_state, trade_risk)

    def get_rules(self) -> dict[str, Any]:
        """
        Get prop firm rules (flat, v1-compatible).

        Returns:
            Rules dictionary
        """
        return self.rules.copy()

    def get_features(self) -> dict[str, Any]:
        """
        Get prop firm features.

        Returns:
            Features dictionary
        """
        return self.features.copy()
