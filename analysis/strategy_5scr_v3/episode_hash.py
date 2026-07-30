"""Identity and material-state hashing for market-episode lifecycles.

Two rules govern everything here:

1. Transport identity never enters lifecycle identity.  ``cluster_id``,
   ``deployment_id``, payload hashes and clean-block ids are deliberately
   excluded, because a new deployment or a new cluster is not a new market
   story.  Once minted, an id survives both.

2. The material-state hash covers only what changes the episode.  Telemetry
   counters and price refreshes are excluded, so a refresh cannot masquerade
   as a material change.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from contracts.strategy_5scr_lifecycle_v2 import MARKET_EPISODE_RULE_VERSION

LIFECYCLE_ID_PREFIX = "5scr-lifecycle:"


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def build_strategy_lifecycle_id(
    *,
    symbol: str,
    opened_at_utc: datetime,
    opening_direction_state: str,
    rule_version: str = MARKET_EPISODE_RULE_VERSION,
) -> str:
    """Mint a stable episode id from market facts only.

    The direction state is the one observed when the episode *opened*; later
    refinement (INCOMPLETE -> BUY) must not re-mint the id.
    """
    basis = "|".join(
        (
            symbol.upper(),
            _iso(opened_at_utc),
            opening_direction_state.upper(),
            rule_version,
        )
    )
    return LIFECYCLE_ID_PREFIX + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def build_material_state_hash(
    *,
    symbol: str,
    state: str,
    direction_state: str,
    opened_at_utc: datetime,
    last_material_event_at_utc: datetime,
    rule_version: str = MARKET_EPISODE_RULE_VERSION,
) -> str:
    """Hash the episode's material state.

    Excludes event_count, clean_block_count, watch_count, cluster ids,
    deployment ids and prices: none of those change what the episode *is*.
    """
    basis = "|".join(
        (
            symbol.upper(),
            state.upper(),
            direction_state.upper(),
            _iso(opened_at_utc),
            _iso(last_material_event_at_utc),
            rule_version,
        )
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


__all__ = [
    "LIFECYCLE_ID_PREFIX",
    "build_material_state_hash",
    "build_strategy_lifecycle_id",
]
