"""
Risk Profile - Per-account risk configuration stored in Redis.

Supports FIXED and SPLIT risk modes. Dashboard writes profile,
Risk Engine reads it. Redis = single source of truth.
"""

import json

from dataclasses import asdict, dataclass
from enum import StrEnum

from loguru import logger

from risk.exceptions import RiskException
from storage.redis_client import RedisClient


class RiskMode(StrEnum):
    """Risk allocation mode."""

    FIXED = "FIXED"
    SPLIT = "SPLIT"


@dataclass(frozen=True)
class RiskProfile:
    """
    Immutable risk profile for a trading account.

    Attributes
    ----------
    risk_per_trade : float
        Risk % per trade (e.g., 0.7 means 0.7%)
    max_daily_dd : float
        Max daily drawdown % (e.g., 5.0 means 5%)
    max_total_dd : float
        Max total drawdown % (e.g., 10.0 means 10%)
    max_open_trades : int
        Maximum concurrent open trades
    risk_mode : RiskMode
        FIXED (single entry) or SPLIT (dual entry)
    split_ratio : tuple[float, float]
        Risk allocation ratio for SPLIT mode (must sum to 1.0)
    """

    risk_per_trade: float = 0.7
    max_daily_dd: float = 5.0
    max_total_dd: float = 10.0
    max_open_trades: int = 1
    risk_mode: RiskMode = RiskMode.FIXED
    split_ratio: tuple[float, float] = (0.4, 0.6)

    def __post_init__(self) -> None:
        """Validate profile constraints."""
        if self.risk_per_trade <= 0 or self.risk_per_trade > 5.0:
            raise RiskException(f"risk_per_trade must be 0 < x <= 5.0, got {self.risk_per_trade}")
        if self.max_daily_dd <= 0 or self.max_daily_dd > 20.0:
            raise RiskException(f"max_daily_dd must be 0 < x <= 20.0, got {self.max_daily_dd}")
        if self.max_total_dd <= 0 or self.max_total_dd > 30.0:
            raise RiskException(f"max_total_dd must be 0 < x <= 30.0, got {self.max_total_dd}")
        if self.max_open_trades < 1 or self.max_open_trades > 5:
            raise RiskException(f"max_open_trades must be 1-5, got {self.max_open_trades}")
        if self.risk_mode == RiskMode.SPLIT:
            total = sum(self.split_ratio)
            if abs(total - 1.0) > 0.001:
                raise RiskException(
                    f"split_ratio must sum to 1.0, got {self.split_ratio} = {total}"
                )

    def to_dict(self) -> dict:
        """Serialize for Redis storage."""
        data = asdict(self)
        data["risk_mode"] = self.risk_mode.value
        data["split_ratio"] = list(self.split_ratio)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "RiskProfile":
        """Deserialize from Redis storage."""
        data["risk_mode"] = RiskMode(data["risk_mode"])
        data["split_ratio"] = tuple(data["split_ratio"])
        return cls(**data)


_REDIS_KEY_PREFIX = "wolf15:risk:profile:"


def save_risk_profile(
    account_id: str,
    profile: RiskProfile,
) -> None:
    """Save risk profile to Redis."""
    redis = RedisClient()
    key = f"{_REDIS_KEY_PREFIX}{account_id}"
    redis.set(key, json.dumps(profile.to_dict()))
    logger.info(
        "Risk profile saved",
        account_id=account_id,
        risk_mode=profile.risk_mode.value,
        risk_per_trade=profile.risk_per_trade,
    )


def load_risk_profile(account_id: str) -> RiskProfile:
    """Load risk profile from Redis. Returns default if not found."""
    redis = RedisClient()
    key = f"{_REDIS_KEY_PREFIX}{account_id}"
    raw = redis.get(key)
    if raw:
        return RiskProfile.from_dict(json.loads(raw))
    logger.warning(
        "No risk profile found, using default",
        account_id=account_id,
    )
    return RiskProfile()
