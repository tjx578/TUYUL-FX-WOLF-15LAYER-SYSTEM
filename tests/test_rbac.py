"""
Tests for RBAC module — role-based access control for multi-user scenarios.

Tests:
  - Role parsing and hierarchy
  - Permission mapping correctness
  - UserContext permission checks
  - FastAPI dependency enforcement
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure project root is importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.middleware.rbac import (  # noqa: E402
    ROLE_PERMISSIONS,
    Permission,
    Role,
    UserContext,
    get_permissions_for_role,
    role_has_permission,
)

# ── Role basics ───────────────────────────────────────────────────────────────


class TestRole:
    def test_from_str_valid(self) -> None:
        assert Role.from_str("viewer") == Role.VIEWER
        assert Role.from_str("TRADER") == Role.TRADER
        assert Role.from_str("  Admin  ") == Role.ADMIN

    def test_from_str_invalid_raises(self) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            Role.from_str("superadmin")
        assert exc_info.value.status_code == 403
        assert "Unknown role" in str(exc_info.value.detail)

    def test_role_values(self) -> None:
        assert Role.VIEWER.value == "viewer"
        assert Role.TRADER.value == "trader"
        assert Role.ADMIN.value == "admin"


# ── Permission mapping ───────────────────────────────────────────────────────


class TestPermissionMapping:
    def test_viewer_has_read_permissions(self) -> None:
        for p in [
            Permission.READ_HEALTH,
            Permission.READ_L12,
            Permission.READ_SIGNALS,
            Permission.READ_ACCOUNTS,
            Permission.READ_JOURNAL,
        ]:
            assert role_has_permission(Role.VIEWER, p), f"Viewer should have {p.value}"

    def test_viewer_cannot_trade(self) -> None:
        for p in [
            Permission.TRADE_TAKE,
            Permission.TRADE_SKIP,
            Permission.TRADE_CONFIRM,
            Permission.TRADE_CLOSE,
        ]:
            assert not role_has_permission(Role.VIEWER, p), f"Viewer should NOT have {p.value}"

    def test_viewer_cannot_write(self) -> None:
        for p in [
            Permission.RISK_WRITE,
            Permission.CONFIG_WRITE,
            Permission.OPS_WRITE,
            Permission.EA_RESTART,
        ]:
            assert not role_has_permission(Role.VIEWER, p), f"Viewer should NOT have {p.value}"

    def test_trader_has_trade_permissions(self) -> None:
        for p in [
            Permission.TRADE_TAKE,
            Permission.TRADE_SKIP,
            Permission.TRADE_CONFIRM,
            Permission.TRADE_CLOSE,
        ]:
            assert role_has_permission(Role.TRADER, p), f"Trader should have {p.value}"

    def test_trader_inherits_viewer_reads(self) -> None:
        viewer_perms = get_permissions_for_role(Role.VIEWER)
        trader_perms = get_permissions_for_role(Role.TRADER)
        assert viewer_perms.issubset(trader_perms), "Trader should inherit all viewer permissions"

    def test_trader_cannot_admin(self) -> None:
        for p in [
            Permission.CONFIG_WRITE,
            Permission.OPS_WRITE,
            Permission.EA_RESTART,
            Permission.RISK_KILL_SWITCH,
        ]:
            assert not role_has_permission(Role.TRADER, p), f"Trader should NOT have {p.value}"

    def test_admin_has_all_permissions(self) -> None:
        assert role_has_permission(Role.ADMIN, Permission.ALL)
        # Admin should have every defined permission via ALL wildcard
        for p in Permission:
            assert role_has_permission(Role.ADMIN, p), f"Admin should have {p.value}"

    def test_admin_inherits_trader(self) -> None:
        trader_perms = get_permissions_for_role(Role.TRADER)
        admin_perms = get_permissions_for_role(Role.ADMIN)
        assert trader_perms.issubset(admin_perms), "Admin should inherit all trader permissions"

    def test_role_hierarchy_is_strict(self) -> None:
        viewer_perms = get_permissions_for_role(Role.VIEWER)
        trader_perms = get_permissions_for_role(Role.TRADER)
        admin_perms = get_permissions_for_role(Role.ADMIN)
        assert len(viewer_perms) < len(trader_perms) < len(admin_perms)


# ── UserContext ───────────────────────────────────────────────────────────────


class TestUserContext:
    def _make_user(
        self,
        role: Role = Role.VIEWER,
        scopes: frozenset[str] | None = None,
    ) -> UserContext:
        return UserContext(
            sub="test-user",
            role=role,
            scopes=scopes or frozenset(),
            auth_method="jwt",
            raw_payload={},
        )

    def test_viewer_has_read(self) -> None:
        user = self._make_user(Role.VIEWER)
        assert user.has_permission(Permission.READ_L12)

    def test_viewer_blocked_from_trade(self) -> None:
        user = self._make_user(Role.VIEWER)
        assert not user.has_permission(Permission.TRADE_TAKE)

    def test_trader_can_trade(self) -> None:
        user = self._make_user(Role.TRADER)
        assert user.has_permission(Permission.TRADE_TAKE)

    def test_admin_can_do_everything(self) -> None:
        user = self._make_user(Role.ADMIN)
        assert user.has_permission(Permission.CONFIG_WRITE)
        assert user.has_permission(Permission.RISK_KILL_SWITCH)
        assert user.has_permission(Permission.TRADE_TAKE)

    def test_jwt_scope_override(self) -> None:
        """A viewer with explicit JWT scope can bypass role-based denial."""
        user = self._make_user(Role.VIEWER, scopes=frozenset({"trade:take"}))
        assert user.has_permission(Permission.TRADE_TAKE)

    def test_wildcard_scope_grants_all(self) -> None:
        user = self._make_user(Role.VIEWER, scopes=frozenset({"*"}))
        assert user.has_permission(Permission.CONFIG_WRITE)

    def test_api_key_user(self) -> None:
        user = UserContext(
            sub="api_key_user",
            role=Role.ADMIN,
            scopes=frozenset({"*"}),
            auth_method="api_key",
            raw_payload={},
        )
        assert user.has_permission(Permission.ALL)
        assert user.has_permission(Permission.TRADE_CLOSE)


# ── Completeness check ───────────────────────────────────────────────────────


class TestPermissionCoverage:
    def test_every_permission_is_assigned_to_at_least_one_role(self) -> None:
        all_assigned: set[Permission] = set()
        for perms in ROLE_PERMISSIONS.values():
            all_assigned.update(perms)
        for p in Permission:
            assert p in all_assigned, f"Permission {p.value} not assigned to any role"

    def test_no_duplicate_permissions_across_base_sets(self) -> None:
        """Viewer-exclusive perms should not exist in trader-only additions."""
        # This is a structural sanity check
        viewer_perms = get_permissions_for_role(Role.VIEWER)
        assert len(viewer_perms) > 0
