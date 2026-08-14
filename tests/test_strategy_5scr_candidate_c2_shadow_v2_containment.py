"""Containment gates for full C2 SHADOW risk authority before C3."""

from __future__ import annotations

import ast
import os
from functools import cache
from pathlib import Path

import pytest

from contracts.strategy_5scr_candidate_c2_shadow_v2 import (
    C2ShadowFinalSignalV2,
    C2ShadowRiskReservationV2,
)
from storage.strategy_5scr_candidate_c2_shadow_v2_repository import (
    _CONSTRAINT_TABLES,
    C2_SHADOW_ONLY_FLAG,
    C2_SHADOW_WRITER_FLAG,
    CandidateC2ShadowV2RuntimeConfig,
    CandidateC2ShadowV2SchemaStatus,
    _fingerprint,
    _normalize_sql,
)

ROOT = Path(__file__).resolve().parents[1]
P7_RUNTIME = (
    ROOT / "contracts" / "strategy_5scr_candidate_c2_shadow_v2.py",
    ROOT / "analysis" / "strategy_5scr_candidate_c2_shadow_v2.py",
    ROOT / "storage" / "strategy_5scr_candidate_c2_shadow_v2_repository.py",
)
P7_MIGRATION = ROOT / "storage" / "migrations" / "versions" / "20260813_02_5scr_candidate_c2_shadow_v2.py"
P7_REPOSITORY_MODULE = "storage.strategy_5scr_candidate_c2_shadow_v2_repository"

_NON_PRODUCTION_PYTHON_ROOTS = frozenset({"tests", "artifacts", "docs", "local", "__pycache__"})
_PYTHON_WALK_PRUNE = frozenset({"__pycache__", "node_modules"})
_ACTIVATION_TEXT_SUFFIXES = frozenset({".env", ".ini", ".json", ".ps1", ".py", ".sh", ".toml", ".yaml", ".yml"})


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


@cache
def _production_python_files() -> tuple[Path, ...]:
    paths: set[Path] = set()
    for current, directories, filenames in os.walk(ROOT, topdown=True):
        current_path = Path(current)
        if current_path == ROOT:
            directories[:] = [
                name for name in directories if not name.startswith(".") and name not in _NON_PRODUCTION_PYTHON_ROOTS
            ]
        else:
            directories[:] = [
                name for name in directories if not name.startswith(".") and name not in _PYTHON_WALK_PRUNE
            ]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            if current_path == ROOT and (filename == "conftest.py" or filename.startswith("._")):
                continue
            paths.add((current_path / filename).resolve())
    return tuple(sorted(paths))


def _activation_files() -> tuple[Path, ...]:
    paths = set(_production_python_files())
    for pattern in (
        "railway*",
        "Dockerfile*",
        "docker-compose*",
        ".dockerignore",
        ".env.example",
        ".railwayignore",
        "pyproject.toml",
    ):
        paths.update(path.resolve() for path in ROOT.glob(pattern) if path.is_file())
    for root_name in ("deploy", "scripts", "services", "startup"):
        directory = ROOT / root_name
        if not directory.exists():
            continue
        paths.update(
            path.resolve()
            for path in directory.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix.lower() in _ACTIVATION_TEXT_SUFFIXES
        )
    return tuple(sorted(paths))


def test_p7_has_no_legacy_risk_command_or_ea_dependency() -> None:
    forbidden = (
        "analysis.strategy_5scr_pressure_to_tradeplan",
        "analysis.strategy_5scr_m1_outcome",
        "contracts.strategy_5scr_pressure",
        "contracts.strategy_5scr_risk_reservation",
        "storage.strategy_5scr_risk_reservation_repository",
        "execution.mt5_risk_command_producer",
        "execution.mt5_command_promotion",
        "execution.mt5_operator_shadow_wiring",
        "services",
        "ea_interface",
    )
    imported = set().union(*(_imports(path) for path in P7_RUNTIME))
    assert not any(module == item or module.startswith(item + ".") for module in imported for item in forbidden)


def test_p7_strategy_and_risk_authority_cannot_authorize_commands_or_broker() -> None:
    reservation = C2ShadowRiskReservationV2.model_fields
    signal = C2ShadowFinalSignalV2.model_fields
    assert reservation["risk_authority"].default is True
    assert reservation["valid_for_execution"].default is True
    assert reservation["broker_execution_authority"].default is False
    assert reservation["command_authority"].default is False
    assert signal["signal_valid"].default is True
    assert signal["valid_for_execution"].default is True
    assert signal["broker_execution_authority"].default is False
    assert signal["command_authority"].default is False
    assert signal["delivery_authority"].default is False
    assert signal["next_required_stage"].default == "C3_MANUAL_SHADOW_PROMOTION"


def test_p7_has_no_existing_production_consumer() -> None:
    module_names = (
        "contracts.strategy_5scr_candidate_c2_shadow_v2",
        "analysis.strategy_5scr_candidate_c2_shadow_v2",
        P7_REPOSITORY_MODULE,
    )
    allowed = {path.resolve() for path in (*P7_RUNTIME, P7_MIGRATION)}
    consumers: list[str] = []
    for path in _production_python_files():
        if path in allowed:
            continue
        source = path.read_text(encoding="utf-8")
        if any(name in source for name in module_names):
            consumers.append(path.relative_to(ROOT).as_posix())
    assert consumers == []


def test_p7_files_do_not_write_c3_runtime_tables_or_call_broker_effects() -> None:
    forbidden_symbols = (
        "OrderSend",
        "MT5RiskCommandProducer",
        "OperatorControlledShadowAuthorityV1",
    )
    forbidden_writes = tuple(
        f"{verb} {table}"
        for verb in ("insert into", "update", "delete from")
        for table in ("execution_commands", "execution_reports", "broker_entities")
    )
    for path in (*P7_RUNTIME, P7_MIGRATION):
        source = path.read_text(encoding="utf-8")
        assert not any(item in source for item in forbidden_symbols), path
        normalized = " ".join(source.lower().split())
        assert not any(item in normalized for item in forbidden_writes), path


def test_p7_runtime_is_default_off_and_shadow_only() -> None:
    defaults = CandidateC2ShadowV2RuntimeConfig.from_env({})
    assert defaults.enabled is False
    assert defaults.shadow_only is True
    defaults.validate()
    with pytest.raises(RuntimeError, match="C2_SHADOW_V2_SHADOW_ONLY_REQUIRED"):
        CandidateC2ShadowV2RuntimeConfig(enabled=True, shadow_only=False).validate()


def test_p7_catalog_fingerprint_binds_exact_catalog_bytes() -> None:
    canonical = "SELECT  Foo\nFROM Bar"
    assert _normalize_sql(canonical) == canonical
    assert _fingerprint(canonical) == _fingerprint(canonical)
    assert _fingerprint(canonical) != _fingerprint("select foo from bar")

    behavior_changes = (
        ("SELECT 'ACTIVE'", "select 'active'"),
        ("SELECT 'It''s ACTIVE'", "select 'It''s active'"),
        ('SELECT "Mixed""Case"', 'select "mixed""case"'),
        ("DO $$BEGIN RAISE NOTICE 'ACTIVE'; END$$", "do $$begin raise notice 'active'; end$$"),
        (
            "CREATE FUNCTION f() RETURNS void AS $Body$\nBEGIN  NULL;\nEND\n$Body$ LANGUAGE plpgsql",
            "create function f() returns void as $Body$\nbegin null;\nend\n$Body$ language plpgsql",
        ),
        ("-- guard\nRAISE EXCEPTION 'blocked';", "-- guard RAISE EXCEPTION 'blocked';"),
        ("/* guard */ RAISE EXCEPTION 'blocked';", "/* guard RAISE EXCEPTION 'blocked'; */"),
    )
    for canonical, drifted in behavior_changes:
        assert _fingerprint(canonical) != _fingerprint(drifted)


def test_p7_readiness_rejects_non_durable_relation_storage() -> None:
    empty = {
        "missing_tables": (),
        "missing_columns": (),
        "invalid_columns": (),
        "missing_constraints": (),
        "invalid_constraints": (),
        "missing_indexes": (),
        "invalid_indexes": (),
        "missing_triggers": (),
        "invalid_triggers": (),
    }
    assert CandidateC2ShadowV2SchemaStatus(invalid_tables=(), **empty).ready is True
    assert (
        CandidateC2ShadowV2SchemaStatus(
            invalid_tables=("strategy_5scr_final_signal_outbox_v2",),
            **empty,
        ).ready
        is False
    )
    repository = (ROOT / "storage" / "strategy_5scr_candidate_c2_shadow_v2_repository.py").read_text(encoding="utf-8")
    for catalog_field in ("cls.relkind", "cls.relpersistence", "cls.relispartition"):
        assert catalog_field in repository
    assert 'str(_row(item, "relkind")) != "r"' in repository
    assert 'str(_row(item, "relpersistence")) != "p"' in repository
    assert 'f"p6:{item}" for item in parent.invalid_tables' in repository


def test_p7_readiness_pins_dependency_authority_cardinality() -> None:
    assert {
        "executor_account_snapshots_pkey": "executor_account_snapshots",
        "executor_instances_pkey": "executor_instances",
        "executor_bridge_governance_pkey": "executor_bridge_governance",
        "ck_executor_governance_singleton": "executor_bridge_governance",
    }.items() <= _CONSTRAINT_TABLES.items()


def test_p7_evaluation_candidate_fk_has_exact_child_index() -> None:
    migration = P7_MIGRATION.read_text(encoding="utf-8")
    expected = """op.create_index(
        "ix_5scr_c2_evaluation_v2_candidate_scope",
        EVALUATION,
        _CANDIDATE_SCOPE,
    )"""
    assert expected in migration
    assert 'op.drop_index("ix_5scr_c2_evaluation_v2_candidate_scope", table_name=EVALUATION)' in migration
    repository = (ROOT / "storage" / "strategy_5scr_candidate_c2_shadow_v2_repository.py").read_text(encoding="utf-8")
    assert '"ix_5scr_c2_evaluation_v2_candidate_scope": EVALUATION_TABLE' in repository


def test_p7_database_pins_complete_dark_final_signal_authority_shape() -> None:
    migration = (
        Path(__file__).parents[1] / "storage" / "migrations" / "versions" / "20260813_02_5scr_candidate_c2_shadow_v2.py"
    ).read_text(encoding="utf-8")
    for required in (
        "(payload ->> 'event'='signal_json') IS TRUE",
        "(payload ->> 'signal_valid')::boolean IS TRUE",
        "(payload ->> 'is_final_signal')::boolean IS TRUE",
        "(payload ->> 'execution_valid_now')::boolean IS TRUE",
        "(payload ->> 'valid_for_execution')::boolean IS TRUE",
        "(payload ->> 'risk_authority')::boolean IS TRUE",
        "(payload ->> 'execution_mode'='SHADOW') IS TRUE",
        "(payload ->> 'next_required_stage'='C3_MANUAL_SHADOW_PROMOTION') IS TRUE",
        "(payload ->> 'broker_execution_authority')::boolean IS FALSE",
        "(payload ->> 'command_authority')::boolean IS FALSE",
        "(payload ->> 'delivery_authority')::boolean IS FALSE",
    ):
        assert required in migration


def test_p7_database_pins_canonical_fractional_risk_policy() -> None:
    migration = P7_MIGRATION.read_text(encoding="utf-8")
    for required in (
        "policy_id='5scr.c2-shadow.parent-only.v2'",
        "risk_percent_per_entry = 0.05",
        "risk_unit_usd = balance_base * risk_percent_per_entry",
        "max_campaign_risk_usd = risk_unit_usd * 2",
        "max_campaign_risk_usd = balance_base * 0.10",
    ):
        assert required in migration


def test_p7_database_cross_authority_guards_are_bidirectional_and_cleanup_safe() -> None:
    migration = " ".join(P7_MIGRATION.read_text(encoding="utf-8").lower().split())
    repository = (ROOT / "storage" / "strategy_5scr_candidate_c2_shadow_v2_repository.py").read_text(encoding="utf-8")
    reservation_definition = migration.split("op.create_table( reservation,", 1)[1].split(
        'op.create_index("ix_5scr_risk_reservation_v2_account_expiry"', 1
    )[0]
    assert 'sa.column("state", sa.string(length=32), nullable=false)' in reservation_definition
    assert "reconciliation_required" in reservation_definition
    guards = (
        "trg_5scr_guard_execution_command_against_c2_v2",
        "trg_5scr_guard_executor_identity_against_c2_v2",
        "trg_5scr_guard_legacy_campaign_risk_against_c2_v2",
        "trg_5scr_guard_legacy_reservation_against_c2_v2",
    )
    for guard in guards:
        assert f"create trigger {guard}" in migration
        assert guard in migration
        assert guard in repository
    assert "drop trigger if exists {trigger}" in migration
    assert "drop function if exists {function}()" in migration

    assert (
        "new.state not in ('rejected','shadow_completed','shadow_rejected')" in migration
        and "before insert or update on execution_commands" in migration
    )
    assert "if tg_op='update' and not conflicts_with_c2 then" in migration
    assert "where account_id=old.account_id and state='active'" in migration
    assert "where account_id=old.account_id and state='reserved'" in migration
    assert "from executor_instances where executor_id=new.executor_id" in migration
    assert "from executor_instances where executor_id=old.executor_id" in migration
    assert "new.account_id is distinct from old.account_id" in migration
    assert "new.executor_id is distinct from old.executor_id" in migration
    assert "ck_execution_command_executor_account_binding_c2_v2" in migration
    assert "handoff.executor_id=new.executor_id and risk_lock.state='active'" in migration
    assert "where executor_id=new.executor_id and state='reserved'" in migration
    assert "handoff.executor_id=old.executor_id and risk_lock.state='active'" in migration
    assert "where executor_id=old.executor_id and state='reserved'" in migration
    assert "before update on executor_instances" in migration
    assert "new.broker_server is distinct from old.broker_server" in migration
    assert "ck_executor_identity_no_live_c2_shadow_v2" in migration
    assert 'op.create_index("ix_5scr_c2_handoff_v2_executor", handoff, ["executor_id", "handoff_id"])' in migration
    assert (
        'op.create_index("ix_5scr_c2_reservation_v2_executor_state", reservation, ["executor_id", "state"])'
        in migration
    )
    assert (
        "if new.state='active' then" in migration
        and "before insert or update on strategy_5scr_campaign_risk_locks" in migration
    )
    assert (
        "if new.state in ('held','consumed','open') then" in migration
        and "before insert or update on strategy_5scr_risk_reservations" in migration
    )
    assert migration.count("pg_advisory_xact_lock(hashtextextended(new.account_id,0))") == 2
    # Legacy terminal cleanup is outside the guarded authority-capable states.
    assert "new.state in ('closed'" not in migration
    assert "new.state in ('released','expired')" not in migration
    for lifecycle_guard in (
        "trg_5scr_campaign_risk_lock_update_v1",
        "trg_5scr_risk_reservation_update_v1",
    ):
        assert lifecycle_guard in repository
    normalized_repository = " ".join(repository.lower().split())
    assert '"execution_commands": frozenset({"command_id", "executor_id",' in normalized_repository
    assert "c.account_id=$1 or c.executor_id=$4::uuid" in normalized_repository
    assert "from executor_instances command_executor" in normalized_repository
    assert "command_executor.executor_id=c.executor_id" in normalized_repository
    assert '"ix_5scr_c2_handoff_v2_executor": handoff_table' in normalized_repository
    assert '"ix_5scr_c2_reservation_v2_executor_state": reservation_table' in normalized_repository
    # load, durable-existing retry preflight, and new-admission processing all
    # preserve the executor-before-governance lock order.
    assert normalized_repository.count("from executor_instances where executor_id=$1::uuid for no key update") == 3
    assert "from executor_instances where executor_id=$1::uuid for update" not in normalized_repository


def test_p7_terminal_audit_clocks_never_come_from_incoming_or_broker_evidence() -> None:
    repository_path = ROOT / "storage" / "strategy_5scr_candidate_c2_shadow_v2_repository.py"
    repository = repository_path.read_text(encoding="utf-8")
    tree = ast.parse(repository)
    terminal_clocks: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "_terminalize" or len(node.args) < 3:
            continue
        terminal_clocks.append(ast.unparse(node.args[2]))

    assert terminal_clocks
    for clock in terminal_clocks:
        assert "captured_at_utc" not in clock
        assert "evidence.decision_at_utc" not in clock
        assert "occurred_at" not in clock
    # Snapshot/governance reconciliation is stamped by PostgreSQL only after
    # the relevant locks and fences have been acquired.
    assert any("transaction_at" in clock for clock in terminal_clocks)
    assert any("liveness_at" in clock for clock in terminal_clocks)
    assert any("commit_at" in clock for clock in terminal_clocks)
    assert any("reconciliation_at" in clock for clock in terminal_clocks)
    assert "SELECT reserved_at,expires_at" in repository
    assert "terminal_at = max(reserved_at, min(occurred_at, database_now))" in repository
    assert 'if reason == "C2_AUTHORITY_EXPIRED":' in repository
    assert "terminal_at = expires_at" in repository


def test_existing_c2_authority_reconciles_durable_state_before_retry_material() -> None:
    repository = (ROOT / "storage" / "strategy_5scr_candidate_c2_shadow_v2_repository.py").read_text(encoding="utf-8")
    process = repository.index("    async def process_evidence(")
    terminal_parent = repository.index("            if parent.terminal and existing is not None:", process)
    durable_preflight = repository.index(
        "                durable_result = await self._reconcile_existing_before_retry", process
    )
    incoming_snapshot = repository.index(
        "                canonical_evidence = snapshot_candidate_c2_build_evidence_v2", process
    )
    prior_collision = repository.index("            prior = await connection.fetchrow(", process)

    assert terminal_parent < durable_preflight < incoming_snapshot < prior_collision
    helper = repository[repository.index("    async def _reconcile_existing_before_retry(") : process]
    for incoming_material in (
        "admitted_evidence",
        "canonical_evidence",
        "evidence.source_request_id",
        "evidence.decision_at_utc",
        "evidence.account_snapshot",
        "evidence.existing_risk",
    ):
        assert incoming_material not in helper
    assert "reservation = existing.reservation" in helper
    assert "LOCK TABLE execution_commands IN SHARE MODE" in helper
    assert "LOCK TABLE executor_account_snapshots IN SHARE MODE" in helper
    assert "latest = self._snapshot_from_row(latest_row)" in helper
    assert "derived_risk = await self._derive_existing_risk(" in helper
    assert helper.count('CandidateC2ShadowPersistenceResult("INVALIDATED"') >= 6


def test_parent_box_predecessor_integrity_code_is_not_collapsed() -> None:
    repository = (ROOT / "storage" / "strategy_5scr_candidate_c2_shadow_v2_repository.py").read_text(encoding="utf-8")
    start = repository.index("        box = _box_from_row(box_row)")
    end = repository.index("    durable_scope = (", start)
    box_validation = repository[start:end]

    specific = box_validation.index("    except CandidateC2ShadowV2IntegrityError:")
    generic = box_validation.index("    except RuntimeError as exc:")
    assert specific < generic
    assert 'CandidateC2ShadowV2IntegrityError("C2_PARENT_AUTHORITY_DRIFT")' in box_validation


def test_rejection_audit_requires_exact_durable_snapshot_proof() -> None:
    repository = (ROOT / "storage" / "strategy_5scr_candidate_c2_shadow_v2_repository.py").read_text(encoding="utf-8")
    process_start = repository.index("    async def process_evidence(")
    process_end = repository.index("    async def reconcile_terminal(", process_start)
    process = repository[process_start:process_end]

    assert "return await persist_rejection(parent.terminal_reason)" not in process
    assert 'persist_rejection("C2_ACCOUNT_SNAPSHOT_MISSING")' not in process
    assert 'CandidateC2ShadowPersistenceResult("REJECTED", "C2_ACCOUNT_SNAPSHOT_MISSING")' in process
    exact_snapshot_proof = process.index("            if (\n                snapshot != evidence.account_snapshot")
    deferred_rejection = process.index("            if rejection is not None:", exact_snapshot_proof)
    rejection_insert = process.index("                return await persist_rejection(rejection)", deferred_rejection)
    assert exact_snapshot_proof < deferred_rejection < rejection_insert


def test_latest_snapshot_binding_applies_to_existing_authority_retries() -> None:
    repository = (ROOT / "storage" / "strategy_5scr_candidate_c2_shadow_v2_repository.py").read_text(encoding="utf-8")
    process_start = repository.index("    async def process_evidence(")
    process_end = repository.index("    async def reconcile_terminal(", process_start)
    process = repository[process_start:process_end]
    snapshot_read = process.index("            snapshot = self._snapshot_from_row(snapshot_row)")
    liveness_read = process.index("            liveness_at = await self._database_now(connection)", snapshot_read)
    binding = process[snapshot_read:liveness_read]

    assert "existing is None" not in binding
    assert "snapshot != evidence.account_snapshot" in binding
    assert "account_snapshot_authority_hash_v2(snapshot) != evidence.account_snapshot_hash" in binding
    assert '"C2_ACCOUNT_SNAPSHOT_CHANGED_DURING_READ"' in binding


def test_exact_persisted_replay_wins_only_after_durable_preflight() -> None:
    repository = (ROOT / "storage" / "strategy_5scr_candidate_c2_shadow_v2_repository.py").read_text(encoding="utf-8")
    process_start = repository.index("    async def process_evidence(")
    process_end = repository.index("    async def reconcile_terminal(", process_start)
    process = repository[process_start:process_end]
    durable_preflight = process.index("durable_result = await self._reconcile_existing_before_retry")
    prior_start = process.index("            if prior is not None:")
    snapshot_read = process.index("            snapshot = self._snapshot_from_row(snapshot_row)")
    prior = process[prior_start:snapshot_read]

    assert durable_preflight < prior_start < snapshot_read
    assert "saved.evidence_hash != evidence.authority_hash()" in prior
    assert '"DUPLICATE", "C2_EVALUATION_ALREADY_PERSISTED", saved, existing' in prior
    # A new request has no exact saved collision and must still bind to the
    # latest durable snapshot rather than inheriting replay semantics.
    assert '"C2_ACCOUNT_SNAPSHOT_CHANGED_DURING_READ"' in process[snapshot_read:]


def test_p7_has_no_railway_activation_or_service_consumer() -> None:
    allowed = {path.resolve() for path in P7_RUNTIME}
    activation_tokens = (
        C2_SHADOW_WRITER_FLAG,
        C2_SHADOW_ONLY_FLAG,
        P7_REPOSITORY_MODULE,
        "Strategy5SCRCandidateC2ShadowV2Repository",
    )
    leaks: list[str] = []
    for path in _activation_files():
        if path in allowed:
            continue
        source = path.read_text(encoding="utf-8", errors="ignore")
        if any(token in source for token in activation_tokens):
            leaks.append(path.relative_to(ROOT).as_posix())
    assert leaks == []
