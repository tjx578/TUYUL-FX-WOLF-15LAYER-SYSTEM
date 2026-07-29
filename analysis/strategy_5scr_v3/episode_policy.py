"""Grouping policy and rollout flags for market-episode lifecycles.

The 900-second gap is not a new invention: the repository already treats an
M15-sized gap as an episode boundary in ``LegacyEpisodePolicy``.  The two are
kept as separate rule versions on purpose, because they answer different
questions:

``5scr.legacy-m15-gap.v1``
    Replay compatibility for exported data that carries no lineage.

``5scr.market-episode.v1``
    Durable shadow grouping for LIVE strategy analysis.

Sharing a number does not make them the same rule, and a future change to one
must not silently move the other.
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from contracts.strategy_5scr_lifecycle_v2 import MARKET_EPISODE_RULE_VERSION

EPISODE_LIFECYCLE_V2_FLAG = "STRATEGY_5SCR_LIFECYCLE_V2_ENABLED"
EPISODE_SHADOW_ONLY_FLAG = "STRATEGY_5SCR_LIFECYCLE_V2_SHADOW_ONLY"
EPISODE_MAX_GAP_FLAG = "STRATEGY_5SCR_LIFECYCLE_V2_MAX_CONTINUITY_GAP_SECONDS"
EPISODE_DUAL_WRITE_FLAG = "STRATEGY_5SCR_LIFECYCLE_V2_DUAL_WRITE_ENABLED"
EPISODE_METRICS_FLAG = "STRATEGY_5SCR_LIFECYCLE_V2_METRICS_ENABLED"

DEFAULT_EPISODE_MAX_CONTINUITY_GAP_SECONDS = 900


class EpisodePreflightError(RuntimeError):
    """Raised when the rollout flags describe an unsafe configuration."""


class MarketEpisodePolicyV1(BaseModel):
    """Frozen rules deciding whether an event continues an episode."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_version: Literal["5scr.market-episode.v1"] = MARKET_EPISODE_RULE_VERSION
    #: An episode splits when no *continuity* evidence arrives for this long.
    #: Measured against last_continuity_event_at, not the material clock:
    #: unchanged pressure still proves the story is running.
    max_continuity_gap_seconds: int = Field(default=DEFAULT_EPISODE_MAX_CONTINUITY_GAP_SECONDS, ge=60, le=86_400)


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() == "true"


def episode_lifecycle_v2_enabled() -> bool:
    return _flag(EPISODE_LIFECYCLE_V2_FLAG, "false")


def episode_shadow_only() -> bool:
    return _flag(EPISODE_SHADOW_ONLY_FLAG, "true")


def episode_dual_write_enabled() -> bool:
    return _flag(EPISODE_DUAL_WRITE_FLAG, "false")


def episode_metrics_enabled() -> bool:
    return _flag(EPISODE_METRICS_FLAG, "true")


def resolve_episode_policy() -> MarketEpisodePolicyV1:
    """Build the policy, taking only the gap from the environment."""
    raw = os.getenv(EPISODE_MAX_GAP_FLAG, "").strip()
    if not raw:
        return MarketEpisodePolicyV1()
    try:
        return MarketEpisodePolicyV1(max_continuity_gap_seconds=int(raw))
    except (TypeError, ValueError) as exc:
        raise EpisodePreflightError(f"{EPISODE_MAX_GAP_FLAG} must be an integer number of seconds") from exc


def assert_episode_rollout_is_safe(*, execution_enabled: bool) -> None:
    """Refuse a configuration where V2 could reach execution.

    Phase one is shadow-only by construction.  Rather than trust every call
    site to check, the unsafe combination is rejected at startup.
    """
    if episode_lifecycle_v2_enabled() and not episode_shadow_only() and execution_enabled:
        raise EpisodePreflightError(
            "STRATEGY_5SCR_LIFECYCLE_V2_ENABLED with shadow_only=false is not permitted while execution is enabled"
        )


__all__ = [
    "DEFAULT_EPISODE_MAX_CONTINUITY_GAP_SECONDS",
    "EPISODE_DUAL_WRITE_FLAG",
    "EPISODE_LIFECYCLE_V2_FLAG",
    "EPISODE_MAX_GAP_FLAG",
    "EPISODE_METRICS_FLAG",
    "EPISODE_SHADOW_ONLY_FLAG",
    "EpisodePreflightError",
    "MarketEpisodePolicyV1",
    "assert_episode_rollout_is_safe",
    "episode_dual_write_enabled",
    "episode_lifecycle_v2_enabled",
    "episode_metrics_enabled",
    "episode_shadow_only",
    "resolve_episode_policy",
]
