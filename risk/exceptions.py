"""
Risk Management Domain Exceptions

Custom exception classes for the risk management system.
All exceptions inherit from a base RiskError for easy catching.
"""


class RiskError(Exception):
    """Base exception for all risk management errors."""


# Backward-compatible alias (keep until all imports are refactored)
RiskException = RiskError


class DrawdownLimitExceeded(RiskError):  # noqa: N818
    """Raised when drawdown exceeds configured limits."""


class CircuitBreakerOpen(RiskError):  # noqa: N818
    """Raised when circuit breaker is in OPEN state and trading is halted."""


class InvalidPositionSize(RiskError):  # noqa: N818
    """Raised when calculated position size is invalid or out of bounds."""


class PropFirmViolation(RiskError):  # noqa: N818
    """Raised when trade would violate prop firm rules."""


class RiskCalculationError(RiskError):
    """Raised when risk calculations fail or produce invalid results."""


class CorrelationRiskExceeded(RiskError):  # noqa: N818
    """Raised when correlated position group exceeds combined exposure limit."""


class SlippageLimitExceeded(RiskError):  # noqa: N818
    """Raised when estimated execution cost makes a trade impractical."""


class TrailingDrawdownBreached(RiskError):  # noqa: N818
    """Raised when trailing drawdown floor is breached."""


class PropFirmConfigError(RiskError):
    """Raised when prop firm configuration is missing, corrupt, or invalid."""


class RedisConnectionError(RiskError):
    """Raised when Redis operations fail critically."""
