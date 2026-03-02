<<<<<<< Updated upstream
"""
Prop Firm Manager

Multi-profile guard system for prop firm rule enforcement.

Purpose:
    - Loads prop firm profiles (FTMO, Aqua Instant Pro, etc.)
    - Evaluates trade proposals against firm rules
    - Returns ALLOW/DENY with severity assessment

Responsibilities:
    - NOT responsible for market analysis or lot calculation
    - ONLY enforces prop firm account rules (DD limits, open trades, etc.)
    - Acts as final validation gate before trade execution

Usage:
    manager = PropFirmManager.for_account("ACC-001")
    result = manager.evaluate_trade(account_state, trade_risk)
    if not result.allowed:
        raise TradeRejected(result.details)
"""
=======
"""Propfirm manager package."""
from propfirm_manager.profile_manager import PropFirmManager

__all__ = ["PropFirmManager"]
>>>>>>> Stashed changes
