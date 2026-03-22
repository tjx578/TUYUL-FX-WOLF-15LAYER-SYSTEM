"""
RBAC — Role-Based Access Control for multi-user scenarios.

Defines:
  - Role enum (viewer, trader, admin)
  - Permission enum (granular action identifiers)
  - Role → Permission mapping (single source of truth)
  - FastAPI dependencies for route-level enforcement

Constitutional constraint: RBAC never grants market decision authority.
Dashboard/EA cannot override Layer-12 verdicts regardless of role.

Usage in routers:
    from api.middleware.rbac import require_role, require_permission, Role, Permission

    @router.get("/...", dependencies=[Depends(require_role(Role.TRADER))])
    async def my_route(): ...

    @router.post("/...", dependencies=[Depends(require_permission(Permission.TRADE_TAKE))])
    async def take_trade(): ...
"""

from __future__ import annotations

import enum
from typing import Any, cast

from fastapi import Depends, Header, HTTPException

from .auth import decode_token, validate_api_key

# ── Roles ─────────────────────────────────────────────────────────────────────


class Role(enum.StrEnum):
    """System roles — ordered by privilege level."""

    VIEWER = "viewer"
    TRADER = "trader"
    ADMIN = "admin"

    @classmethod
    def from_str(cls, value: str) -> Role:
        cleaned = value.strip().lower()
        try:
            return cls(cleaned)
        except ValueError:
            raise HTTPException(
                status_code=403,
                detail=f"Unknown role: {value!r}. Allowed: {', '.join(r.value for r in cls)}",
            ) from None


# ── Permissions ───────────────────────────────────────────────────────────────


class Permission(enum.StrEnum):
    """Granular action identifiers for scope-based checks."""

    # Read
    READ_HEALTH = "read:health"
    READ_L12 = "read:l12"
    READ_SIGNALS = "read:signals"
    READ_ACCOUNTS = "read:accounts"
    READ_JOURNAL = "read:journal"
    READ_INSTRUMENTS = "read:instruments"
    READ_CALENDAR = "read:calendar"
    READ_PROP = "read:prop"
    READ_RISK = "read:risk"
    READ_EA = "read:ea"
    READ_DASHBOARD = "read:dashboard"
    READ_METRICS = "read:metrics"
    READ_REDIS = "read:redis"
    READ_CONFIG = "read:config"

    # Trade lifecycle
    TRADE_TAKE = "trade:take"
    TRADE_SKIP = "trade:skip"
    TRADE_CONFIRM = "trade:confirm"
    TRADE_CLOSE = "trade:close"

    # Risk management
    RISK_WRITE = "risk:write"
    RISK_KILL_SWITCH = "risk:kill_switch"

    # EA control
    EA_RESTART = "ea:restart"
    EA_SAFE_MODE = "ea:safe_mode"

    # Config / admin
    CONFIG_WRITE = "config:write"
    ACCOUNT_WRITE = "account:write"
    OPS_WRITE = "ops:write"

    # Wildcard (API-key / super-admin)
    ALL = "*"


# ── Role → Permission mapping ────────────────────────────────────────────────

_VIEWER_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.READ_HEALTH,
        Permission.READ_L12,
        Permission.READ_SIGNALS,
        Permission.READ_ACCOUNTS,
        Permission.READ_JOURNAL,
        Permission.READ_INSTRUMENTS,
        Permission.READ_CALENDAR,
        Permission.READ_PROP,
        Permission.READ_RISK,
        Permission.READ_EA,
        Permission.READ_DASHBOARD,
        Permission.READ_METRICS,
        Permission.READ_CONFIG,
    }
)

_TRADER_PERMISSIONS: frozenset[Permission] = _VIEWER_PERMISSIONS | frozenset(
    {
        Permission.TRADE_TAKE,
        Permission.TRADE_SKIP,
        Permission.TRADE_CONFIRM,
        Permission.TRADE_CLOSE,
        Permission.READ_REDIS,
    }
)

_ADMIN_PERMISSIONS: frozenset[Permission] = _TRADER_PERMISSIONS | frozenset(
    {
        Permission.RISK_WRITE,
        Permission.RISK_KILL_SWITCH,
        Permission.EA_RESTART,
        Permission.EA_SAFE_MODE,
        Permission.CONFIG_WRITE,
        Permission.ACCOUNT_WRITE,
        Permission.OPS_WRITE,
        Permission.ALL,
    }
)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: _VIEWER_PERMISSIONS,
    Role.TRADER: _TRADER_PERMISSIONS,
    Role.ADMIN: _ADMIN_PERMISSIONS,
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def role_has_permission(role: Role, permission: Permission) -> bool:
    """Check if a role has a specific permission."""
    perms = ROLE_PERMISSIONS.get(role, frozenset())
    return Permission.ALL in perms or permission in perms


def get_permissions_for_role(role: Role) -> frozenset[Permission]:
    """Return all permissions granted to a role."""
    return ROLE_PERMISSIONS.get(role, frozenset())


# ── Token → User context ─────────────────────────────────────────────────────


class UserContext:
    """Resolved user identity from a JWT or API key."""

    __slots__ = ("sub", "role", "scopes", "auth_method", "raw_payload")

    def __init__(
        self,
        sub: str,
        role: Role,
        scopes: frozenset[str],
        auth_method: str,
        raw_payload: dict[str, Any],
    ) -> None:
        super().__init__()
        self.sub = sub
        self.role = role
        self.scopes = scopes
        self.auth_method = auth_method
        self.raw_payload = raw_payload

    def has_permission(self, perm: Permission) -> bool:
        # JWT-scope override: if the token carries explicit scopes, check those too
        if perm.value in self.scopes or "*" in self.scopes:
            return True
        return role_has_permission(self.role, perm)


def _extract_user_context(authorization: str | None) -> UserContext:
    """Parse Authorization header into a UserContext."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid Authorization scheme. Use: Bearer <token>")

    # Try JWT first
    payload = decode_token(token)
    if payload is not None:
        role_raw = payload.get("role")
        # Backwards-compat: tokens without role claim → viewer
        role = Role.VIEWER if role_raw is None else Role.from_str(str(role_raw))

        raw_scopes = payload.get("scopes", payload.get("scope", []))
        scopes: set[str] = set()
        if isinstance(raw_scopes, str):
            scopes.update(s for s in raw_scopes.replace(",", " ").split() if s)
        elif isinstance(raw_scopes, list):
            for item in cast(list[object], raw_scopes):
                scope_value = str(item).strip()
                if scope_value:
                    scopes.add(scope_value)

        return UserContext(
            sub=str(payload.get("sub", "user:unknown")),
            role=role,
            scopes=frozenset(scopes),
            auth_method="jwt",
            raw_payload=payload,
        )

    # Fall back to API key → admin
    if validate_api_key(token):
        return UserContext(
            sub="api_key_user",
            role=Role.ADMIN,
            scopes=frozenset({"*"}),
            auth_method="api_key",
            raw_payload={},
        )

    raise HTTPException(status_code=401, detail="Invalid or expired token")


# ── FastAPI Dependencies ──────────────────────────────────────────────────────


def get_current_user(authorization: str = Header(None)) -> UserContext:
    """
    FastAPI dependency: resolve the current user from the Authorization header.

    Returns a UserContext with role + permissions.
    """
    return _extract_user_context(authorization)


def require_role(minimum_role: Role):
    """
    FastAPI dependency factory: require at least the given role.

    Role hierarchy: viewer < trader < admin
    """
    _hierarchy = {Role.VIEWER: 0, Role.TRADER: 1, Role.ADMIN: 2}

    def _check(user: UserContext = Depends(get_current_user)) -> UserContext:  # noqa: B008
        user_level = _hierarchy.get(user.role, -1)
        required_level = _hierarchy.get(minimum_role, 99)
        if user_level < required_level:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{user.role.value}' insufficient. Requires at least '{minimum_role.value}'.",
            )
        return user

    return _check


def require_permission(permission: Permission):
    """
    FastAPI dependency factory: require a specific permission.

    Checks both role-based grants and explicit JWT scopes.
    """

    def _check(user: UserContext = Depends(get_current_user)) -> UserContext:  # noqa: B008
        if not user.has_permission(permission):
            raise HTTPException(
                status_code=403,
                detail=f"Missing required permission: {permission.value}",
            )
        return user

    return _check


def require_any_permission(*permissions: Permission):
    """
    FastAPI dependency factory: require at least ONE of the listed permissions.
    """

    def _check(user: UserContext = Depends(get_current_user)) -> UserContext:  # noqa: B008
        if not any(user.has_permission(p) for p in permissions):
            names = ", ".join(p.value for p in permissions)
            raise HTTPException(
                status_code=403,
                detail=f"Missing required permission. Need one of: {names}",
            )
        return user

    return _check
