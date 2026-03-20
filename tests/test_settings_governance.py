"""
P1-8: Settings Governance Tests
================================
Tests versioned snapshots, immutable audit entries, rollback,
diff computation, domain validation, and service layer.
"""

from __future__ import annotations

import pytest

from api.settings_governance import (
    SettingsAuditEntry,
    SettingsGovernanceRepository,
    SettingsGovernanceService,
    SettingsRollbackRequest,
    SettingsSnapshot,
    SettingsWriteRequest,
)


async def _noop_coro(*args, **kwargs):
    return None


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def repo(monkeypatch):
    r = SettingsGovernanceRepository()
    monkeypatch.setattr(r, "_pg_insert_snapshot", lambda *a, **kw: _noop_coro())
    monkeypatch.setattr(r, "_pg_insert_audit", lambda *a, **kw: _noop_coro())
    return r


@pytest.fixture
def service(repo):
    return SettingsGovernanceService(repo=repo)


# ── Snapshot Model ────────────────────────────────────────────────────────


class TestSettingsSnapshot:
    def test_snapshot_has_auto_id_and_timestamp(self):
        snap = SettingsSnapshot(domain="risk", version=1, settings={"max_risk": 2.0})
        assert snap.snapshot_id.startswith("snap_")
        assert snap.created_at is not None

    def test_snapshot_forbids_extra_fields(self):
        with pytest.raises(Exception):  # noqa: B017
            SettingsSnapshot(domain="risk", version=1, settings={}, extra="nope")  # type: ignore[call-arg]


# ── Audit Entry Model ────────────────────────────────────────────────────


class TestSettingsAuditEntry:
    def test_audit_entry_has_auto_id(self):
        entry = SettingsAuditEntry(
            domain="risk",
            snapshot_id="snap_abc",
            version=1,
            action="CREATE",
            changed_by="admin",
            reason="Initial setup",
        )
        assert entry.audit_id.startswith("saud_")

    def test_audit_entry_rejects_short_reason(self):
        with pytest.raises(Exception):  # noqa: B017
            SettingsAuditEntry(
                domain="risk",
                snapshot_id="snap_abc",
                version=1,
                action="UPDATE",
                changed_by="admin",
                reason="ab",  # min_length=3
            )


# ── Repository ────────────────────────────────────────────────────────────


class TestSettingsGovernanceRepository:
    async def test_save_and_get_current(self, repo):
        snap, audit = await repo.save_snapshot(
            domain="risk",
            settings={"max_risk_per_trade": 2.0},
            changed_by="admin",
            reason="Initial risk settings",
        )
        assert snap.version == 1
        assert snap.domain == "risk"

        current = await repo.get_current("risk")
        assert current is not None
        assert current.version == 1
        assert current.settings["max_risk_per_trade"] == 2.0

    async def test_versioning_increments(self, repo):
        await repo.save_snapshot(domain="risk", settings={"a": 1}, changed_by="admin", reason="version one")
        snap2, _ = await repo.save_snapshot(domain="risk", settings={"a": 2}, changed_by="admin", reason="version two")
        assert snap2.version == 2

        snap3, _ = await repo.save_snapshot(
            domain="risk", settings={"a": 3}, changed_by="admin", reason="version three"
        )
        assert snap3.version == 3

    async def test_get_version(self, repo):
        await repo.save_snapshot(
            domain="pairs", settings={"pairs": ["EURUSD"]}, changed_by="admin", reason="version one"
        )
        await repo.save_snapshot(
            domain="pairs", settings={"pairs": ["EURUSD", "GBPUSD"]}, changed_by="admin", reason="version two"
        )

        v1 = await repo.get_version("pairs", 1)
        assert v1 is not None
        assert v1.settings["pairs"] == ["EURUSD"]

        v2 = await repo.get_version("pairs", 2)
        assert v2 is not None
        assert "GBPUSD" in v2.settings["pairs"]

    async def test_get_version_nonexistent(self, repo):
        result = await repo.get_version("risk", 999)
        assert result is None

    async def test_get_current_empty_domain(self, repo):
        result = await repo.get_current("nonexistent_domain")
        assert result is None

    async def test_audit_trail_recorded(self, repo):
        await repo.save_snapshot(
            domain="risk",
            settings={"a": 1},
            changed_by="admin",
            reason="First update",
            action="CREATE",
        )
        await repo.save_snapshot(
            domain="risk",
            settings={"a": 2},
            changed_by="ops",
            reason="Second update",
            action="UPDATE",
        )

        history = await repo.get_audit_history("risk")
        assert len(history) == 2
        # Most recent first
        assert history[0].changed_by == "ops"
        assert history[1].changed_by == "admin"

    async def test_diff_summary_computed(self, repo):
        await repo.save_snapshot(
            domain="risk",
            settings={"max_risk": 2.0, "stop_loss": 50},
            changed_by="admin",
            reason="version one",
        )
        _, audit = await repo.save_snapshot(
            domain="risk",
            settings={"max_risk": 3.0, "new_field": True},
            changed_by="admin",
            reason="version two",
        )
        diff = audit.diff_summary
        assert diff is not None
        assert "max_risk" in diff["changed"]
        assert diff["changed"]["max_risk"]["old"] == 2.0
        assert diff["changed"]["max_risk"]["new"] == 3.0
        assert "new_field" in diff["added"]
        assert "stop_loss" in diff["removed"]


# ── Service Layer ─────────────────────────────────────────────────────────


class TestSettingsGovernanceService:
    async def test_get_settings_empty(self, service):
        result = await service.get_settings("risk")
        assert result is None

    async def test_update_and_get(self, service):
        req = SettingsWriteRequest(
            settings={"max_risk_per_trade": 2.0},
            changed_by="admin",
            reason="Initial config",
        )
        resp = await service.update_settings("risk", req)
        assert resp.version == 1
        assert resp.domain == "risk"

        fetched = await service.get_settings("risk")
        assert fetched is not None
        assert fetched.version == 1
        assert fetched.settings["max_risk_per_trade"] == 2.0

    async def test_rollback_to_previous_version(self, service):
        # Create v1
        await service.update_settings(
            "risk",
            SettingsWriteRequest(
                settings={"max_risk": 2.0},
                changed_by="admin",
                reason="version one",
            ),
        )
        # Create v2
        await service.update_settings(
            "risk",
            SettingsWriteRequest(
                settings={"max_risk": 5.0},
                changed_by="admin",
                reason="version two - too risky",
            ),
        )

        # Rollback to v1 (creates v3 with v1's settings)
        rollback_resp = await service.rollback_settings(
            "risk",
            SettingsRollbackRequest(
                target_version=1,
                changed_by="admin",
                reason="Reverting risky change",
            ),
        )
        assert rollback_resp.version == 3
        assert rollback_resp.settings["max_risk"] == 2.0

    async def test_rollback_nonexistent_version_raises(self, service):
        await service.update_settings(
            "risk",
            SettingsWriteRequest(settings={"a": 1}, changed_by="admin", reason="version one"),
        )
        with pytest.raises(ValueError, match="not found"):
            await service.rollback_settings(
                "risk",
                SettingsRollbackRequest(
                    target_version=999,
                    changed_by="admin",
                    reason="test",
                ),
            )

    async def test_invalid_domain_raises(self, service):
        with pytest.raises(ValueError, match="Unknown settings domain"):
            await service.get_settings("invalid_domain")

    async def test_allowed_domains(self, service):
        expected = frozenset(
            {
                "risk",
                "pairs",
                "prop_firm",
                "constitution",
                "telegram",
                "finnhub",
                "settings",
                "execution",
            }
        )
        assert expected == service.ALLOWED_DOMAINS

    async def test_audit_history(self, service):
        await service.update_settings(
            "risk",
            SettingsWriteRequest(settings={"a": 1}, changed_by="admin", reason="first"),
        )
        await service.update_settings(
            "risk",
            SettingsWriteRequest(settings={"a": 2}, changed_by="ops", reason="second"),
        )
        history = await service.get_audit_history("risk")
        assert len(history) == 2

    async def test_write_request_validation(self):
        with pytest.raises(Exception):  # noqa: B017
            SettingsWriteRequest(
                settings={"a": 1},
                changed_by="x",  # min_length=2 fail
                reason="valid reason",
            )

    async def test_rollback_request_validation(self):
        with pytest.raises(Exception):  # noqa: B017
            SettingsRollbackRequest(
                target_version=0,  # ge=1 fail
                changed_by="admin",
                reason="valid reason",
            )


# ── Diff Computation ─────────────────────────────────────────────────────


class TestDiffComputation:
    def test_empty_diff_when_same(self):
        diff = SettingsGovernanceRepository._compute_diff(
            SettingsSnapshot(domain="risk", version=1, settings={"a": 1}),
            {"a": 1},
        )
        assert diff["added"] == {}
        assert diff["removed"] == {}
        assert diff["changed"] == {}

    def test_diff_detects_additions(self):
        diff = SettingsGovernanceRepository._compute_diff(
            SettingsSnapshot(domain="risk", version=1, settings={"a": 1}),
            {"a": 1, "b": 2},
        )
        assert "b" in diff["added"]

    def test_diff_detects_removals(self):
        diff = SettingsGovernanceRepository._compute_diff(
            SettingsSnapshot(domain="risk", version=1, settings={"a": 1, "b": 2}),
            {"a": 1},
        )
        assert "b" in diff["removed"]

    def test_diff_detects_changes(self):
        diff = SettingsGovernanceRepository._compute_diff(
            SettingsSnapshot(domain="risk", version=1, settings={"a": 1}),
            {"a": 99},
        )
        assert diff["changed"]["a"]["old"] == 1
        assert diff["changed"]["a"]["new"] == 99
