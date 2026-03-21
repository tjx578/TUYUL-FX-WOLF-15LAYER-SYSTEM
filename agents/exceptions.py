"""Domain exceptions for the Agent Manager subsystem.

All exceptions derive from AgentError to allow broad catch-all handling
while preserving granular error differentiation in callers.
"""

from __future__ import annotations

__all__ = [
    "AgentError",
    "AgentNotFoundError",
    "AgentConflictError",
    "AgentLockError",
    "AgentValidationError",
]


class AgentError(Exception):
    """Base exception for all Agent Manager errors."""


class AgentNotFoundError(AgentError):
    """Raised when a requested agent does not exist."""


class AgentConflictError(AgentError):
    """Raised when an operation conflicts with existing state (e.g. duplicate name)."""


class AgentLockError(AgentError):
    """Raised when a lock/unlock operation is invalid for the current agent state."""


class AgentValidationError(AgentError):
    """Raised when input data fails domain-level validation."""
