"""
Risk Management Domain Exceptions

Custom exception classes for the risk management system.
All exceptions inherit from a base RiskException for easy catching.
"""


class RiskException(Exception):
    """Base exception for all risk management errors."""

    pass


class DrawdownLimitExceeded(RiskException):
    """Raised when drawdown exceeds configured limits."""

    pass


class CircuitBreakerOpen(RiskException):
    """Raised when circuit breaker is in OPEN state and trading is halted."""

    pass


class InvalidPositionSize(RiskException):
    """Raised when calculated position size is invalid or out of bounds."""

    pass


class PropFirmViolation(RiskException):
    """Raised when trade would violate prop firm rules."""

    pass


class RiskCalculationError(RiskException):
    """Raised when risk calculations fail or produce invalid results."""

    pass


class RedisConnectionError(RiskException):
    """Raised when Redis operations fail critically."""

    pass
