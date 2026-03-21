"""Prop firm rule resolver — merges default + plan + phase rules into one object.

Zone: propfirm_manager/ — governance/risk, no market decision authority.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from propfirm_manager.resolved_rules import ResolvedPropRules


class PropFirmRuleResolver:
    """Load and resolve prop firm rules for a specific firm / plan / phase.

    Responsibilities:
        - Load profile YAML for a given firm_code (with caching).
        - Merge ``default_rules`` with plan-specific phase overrides.
        - Return an immutable :class:`ResolvedPropRules` instance.
        - Support v1 (flat ``rules`` key) and v2 (``plans`` + ``default_rules``) formats.

    Example::

        resolver = PropFirmRuleResolver()
        rules = resolver.resolve("aqua_instant_pro", "pro_100k", "funded")
        # rules.max_daily_dd_percent -> 3.0
    """

    _PROFILES_DIR = Path(__file__).parent / "profiles"

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_firms(self) -> list[str]:
        """Return all available firm codes (profile directory names).

        Returns:
            Sorted list of firm code strings.
        """
        return sorted(
            d.name
            for d in self._PROFILES_DIR.iterdir()
            if d.is_dir() and (d / "profile.yaml").exists()
        )

    def list_plans(self, firm_code: str) -> list[str]:
        """Return all plan codes for a given firm.

        For v1 profiles (no ``plans`` key) returns an empty list.

        Args:
            firm_code: Firm identifier, e.g. ``"aqua_instant_pro"``.

        Returns:
            Sorted list of plan code strings.

        Raises:
            FileNotFoundError: If the firm profile does not exist.
        """
        config = self._load_raw(firm_code)
        plans: dict[str, Any] = config.get("plans", {})
        return sorted(plans.keys())

    def list_phases(self, firm_code: str, plan_code: str) -> list[str]:
        """Return all phase names for a given firm + plan.

        For v1 profiles or when the plan is not found returns an empty list.

        Args:
            firm_code: Firm identifier.
            plan_code: Plan identifier.

        Returns:
            Sorted list of phase name strings.

        Raises:
            FileNotFoundError: If the firm profile does not exist.
        """
        config = self._load_raw(firm_code)
        plan: dict[str, Any] = config.get("plans", {}).get(plan_code, {})
        phases: dict[str, Any] = plan.get("phases", {})
        return sorted(phases.keys())

    def resolve(self, firm_code: str, plan_code: str, phase: str) -> ResolvedPropRules:
        """Resolve rules for a specific firm / plan / phase combination.

        Merges ``default_rules`` with any plan+phase-specific overrides.
        If ``plan_code`` or ``phase`` are not found in the YAML the
        ``default_rules`` act as the sole source of truth (no ``KeyError``).

        For v1 profiles (flat ``rules`` key, no ``plans``), ``plan_code`` and
        ``phase`` are used for labelling only.

        Args:
            firm_code: Firm identifier, e.g. ``"ftmo"``.
            plan_code: Plan identifier, e.g. ``"challenge_100k"``.
            phase: Phase name, e.g. ``"funded"``.

        Returns:
            Frozen :class:`ResolvedPropRules` instance.

        Raises:
            FileNotFoundError: If the firm profile YAML does not exist.
            ValueError: If *firm_code* is empty or whitespace.
        """
        if not firm_code or not firm_code.strip():
            raise ValueError("firm_code must be a non-empty string")

        config = self._load_raw(firm_code)
        firm_name: str = config.get("name", firm_code)
        features: dict[str, Any] = config.get("features", {})

        # Build effective default (v1 uses "rules"; v2 uses "default_rules")
        default_rules: dict[str, Any] = dict(
            config.get("default_rules", config.get("rules", {}))
        )

        # Resolve plan metadata
        plans: dict[str, Any] = config.get("plans", {})
        plan_data: dict[str, Any] = plans.get(plan_code, {})
        plan_display_name: str = plan_data.get("display_name", plan_code)
        initial_balance: float = float(plan_data.get("initial_balance", 0.0))
        currency: str = str(plan_data.get("currency", "USD"))

        # Phase-specific overrides (empty dict when plan/phase not found)
        phase_rules: dict[str, Any] = plan_data.get("phases", {}).get(phase, {})

        # Merge: defaults < phase overrides
        merged: dict[str, Any] = {**default_rules, **phase_rules}

        logger.debug(
            f"Resolved rules: firm={firm_code} plan={plan_code} phase={phase} "
            f"(plan_found={bool(plan_data)}, phase_found={bool(phase_rules)})"
        )

        return ResolvedPropRules(
            firm_code=firm_code,
            firm_name=firm_name,
            plan_code=plan_code,
            plan_display_name=plan_display_name,
            phase=phase,
            initial_balance=initial_balance,
            currency=currency,
            max_daily_dd_percent=float(merged.get("max_daily_dd_percent", 5.0)),
            max_total_dd_percent=float(merged.get("max_total_dd_percent", 10.0)),
            drawdown_mode=str(merged.get("drawdown_mode", "FIXED")),
            profit_target_percent=float(merged.get("profit_target_percent", 10.0)),
            consistency_rule_percent=float(merged.get("consistency_rule_percent", 0.0)),
            min_trading_days=int(merged.get("min_trading_days", 0)),
            max_risk_per_trade_percent=float(merged.get("max_risk_per_trade_percent", 1.0)),
            max_open_trades=int(merged.get("max_open_trades", 1)),
            min_rr_required=float(merged.get("min_rr_required", 2.0)),
            news_restriction=bool(merged.get("news_restriction", False)),
            weekend_holding=bool(merged.get("weekend_holding", True)),
            allow_scaling=bool(features.get("allow_scaling", False)),
            allow_split_risk=bool(features.get("allow_split_risk", False)),
        )

    def resolve_for_account(
        self,
        account_risk_state: Any,  # accounts.account_repository.AccountRiskState
    ) -> ResolvedPropRules:
        """Convenience method: resolve rules from an :class:`AccountRiskState`.

        Uses ``prop_firm_code`` and ``phase_mode`` from the account state.
        When the firm has multiple plans the first plan whose
        ``initial_balance`` is closest to (and ≤) the account's balance is
        selected; if none matches, the first available plan is used and
        ``default_rules`` govern the outcome.

        Args:
            account_risk_state: An ``AccountRiskState`` instance.

        Returns:
            Frozen :class:`ResolvedPropRules` instance.

        Raises:
            FileNotFoundError: If the firm profile YAML does not exist.
        """
        firm_code: str = account_risk_state.prop_firm_code
        phase: str = account_risk_state.phase_mode.lower()

        config = self._load_raw(firm_code)
        plans: dict[str, Any] = config.get("plans", {})

        plan_code: str
        if plans:
            balance: float = float(account_risk_state.balance)
            # Pick the plan whose initial_balance is ≤ account balance,
            # preferring the largest matching value (closest match from below).
            # If no plan has an initial_balance ≤ balance (e.g. all plans are
            # larger than the account balance), we fall back to the first plan
            # and let default_rules govern — no error is raised because the
            # resolver is designed to be non-throwing in ambiguous situations.
            best_code: str | None = None
            best_balance: float = -1.0
            for code, plan_data in plans.items():
                plan_balance = float(plan_data.get("initial_balance", 0.0))
                if plan_balance <= balance and plan_balance > best_balance:
                    best_balance = plan_balance
                    best_code = code
            plan_code = best_code or next(iter(plans))
        else:
            plan_code = "default"

        return self.resolve(firm_code, plan_code, phase)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_raw(self, firm_code: str) -> dict[str, Any]:
        """Load (and cache) the raw profile YAML for *firm_code*.

        Args:
            firm_code: Firm identifier.

        Returns:
            Parsed YAML dict.

        Raises:
            FileNotFoundError: If the profile YAML does not exist.
        """
        if firm_code in self._cache:
            return self._cache[firm_code]

        profile_path = self._PROFILES_DIR / firm_code / "profile.yaml"
        if not profile_path.exists():
            raise FileNotFoundError(
                f"Prop firm profile not found for firm_code='{firm_code}': {profile_path}"
            )

        with open(profile_path) as fh:
            config: dict[str, Any] = yaml.safe_load(fh) or {}

        self._cache[firm_code] = config
        logger.debug(f"PropFirmRuleResolver: loaded profile for '{firm_code}'")
        return config
