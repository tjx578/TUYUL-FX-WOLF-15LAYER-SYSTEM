"""P4 contract gates for the durable Channel-B account-binding identity authority.

These are source-and-logic gates. Privilege, projection and read-only-transaction
gates that need a real server live in
``tests/integration/test_channel_b_account_binding_identity_postgres.py``.

The distinction that this whole milestone rests on: ``executor_reconciliation_bindings``
is D0 reconciliation evidence, and ``executor_account_binding_identifiers`` is the
durable Channel-B identity authority. They share the HMAC primitive and nothing else.
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import pytest

from execution import account_binding_identity_repository as identity_repo
from ops.mt5_mcp import account_binding, reconcile
from tests.test_channel_b_reconciliation import (
    DIRECT_IDENTIFIER,
    TEST_KEY_ID,
    WINDOW_FROM,
    WINDOW_TO,
    _broker,
    _database,
    _identity_row,
)

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "storage" / "migrations" / "versions" / "20260911_01_channel_b_account_binding_identity.py"
VERSIONS = ROOT / "storage" / "migrations" / "versions"
PRODUCER = ROOT / "execution" / "account_binding_identity_repository.py"

OTHER_KEY_ID = "rotated-next"
OTHER_IDENTIFIER = "w15ab:v1:" + OTHER_KEY_ID + ":" + ("B" * 43)


def _migration() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def _report(**database_kwargs) -> dict[str, object]:
    return reconcile.reconcile_snapshots(
        database=_database(**database_kwargs),
        broker=_broker(),
        window_from=WINDOW_FROM,
        window_to=WINDOW_TO,
    )


# --- P4-C01 / P4-C02: migration lineage --------------------------------------


def test_migration_declares_a_single_head_on_the_canonical_parent() -> None:
    source = _migration()
    assert 'revision = "20260911_01"' in source
    assert 'down_revision = "20260910_02"' in source

    # No other revision may claim the same parent, or alembic would fork.
    claimants = [
        path.name
        for path in VERSIONS.glob("*.py")
        if path != MIGRATION and 'down_revision = "20260910_02"' in path.read_text(encoding="utf-8")
    ]
    assert claimants == []


# --- P4-C03 / P4-C04: nothing sensitive may reach PostgreSQL -----------------


@pytest.mark.parametrize(
    "forbidden",
    ["account_id", "login_hash", "login_suffix", "snapshot_payload", "credential", "secret", "hmac_key"],
)
def test_identity_table_stores_no_raw_account_or_credential_material(forbidden: str) -> None:
    """Check declared column names, not raw substrings.

    A naive substring test matches account_id inside the binding_source constant
    EXECUTOR_INSTANCE_ACCOUNT_ID, which is a legitimate public value.
    """

    table = _migration()
    table = table[table.index("CREATE TABLE executor_account_binding_identifiers") : table.index("CREATE INDEX")]
    columns = set()
    for line in table.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("CREATE", "PRIMARY KEY", "CONSTRAINT", ")", "CHECK")):
            continue
        columns.add(stripped.split()[0].lower())
    assert forbidden not in columns
    assert columns == {
        "executor_id",
        "key_id",
        "scheme",
        "contract_version",
        "algorithm",
        "identifier",
        "binding_source",
        "broker_server",
        "generated_at",
        "retired_at",
        "producer_version",
    }


def test_no_hmac_key_reaches_sql_or_schema() -> None:
    source = _migration()
    assert account_binding.KEY_ENV not in source
    # The producer reads the key from the environment and passes it only to the
    # in-process primitive; it must never appear in a statement it sends to the server.
    producer = PRODUCER.read_text(encoding="utf-8")
    statements = re.findall(r'"""(.*?)"""', producer, flags=re.DOTALL)
    for statement in statements:
        assert account_binding.KEY_ENV not in statement
        assert "secret_key" not in statement
        assert "account_id" not in statement
        assert "login_hash" not in statement


# --- P4-C05 to P4-C11: canonical contract enforced in the schema -------------


@pytest.mark.parametrize(
    ("gate", "fragment"),
    [
        ("P4-C05", "identifier ~ '^w15ab:v1:[a-z0-9][a-z0-9._-]{0,31}:[A-Za-z0-9_-]{43}$'"),
        ("P4-C06", "key_id ~ '^[a-z0-9][a-z0-9._-]{0,31}$'"),
        ("P4-C07", "scheme = 'w15-account-binding'"),
        ("P4-C08", "contract_version = 'v1'"),
        ("P4-C09", "algorithm = 'HMAC-SHA-256'"),
        ("P4-C10", "binding_source = 'EXECUTOR_INSTANCE_ACCOUNT_ID'"),
    ],
)
def test_schema_constrains_the_canonical_contract(gate: str, fragment: str) -> None:
    assert fragment in _migration(), gate


def test_schema_constants_match_the_shared_primitive() -> None:
    """The migration must not drift from ops.mt5_mcp.account_binding."""

    source = _migration()
    assert f"'{account_binding.SCHEME}'" in source
    assert f"'{account_binding.VERSION}'" in source
    assert f"'{account_binding.ALGORITHM}'" in source
    assert f"'{account_binding.DATABASE_SOURCE}'" in source


def test_embedded_key_id_must_agree_with_the_key_id_column() -> None:
    assert "split_part(identifier, ':', 3) = key_id" in _migration()


def test_primary_key_supports_bounded_key_rotation() -> None:
    """P4-C11: keyed by executor_id AND key_id, unlike the D0 evidence table.

    A single-column executor_id primary key cannot express an overlap where an old
    and a new key are both active, which is what retires a key safely.
    """
    assert "PRIMARY KEY (executor_id, key_id)" in _migration()
    assert "executor_id uuid NOT NULL REFERENCES executor_instances" in _migration()


def test_retirement_is_a_lifecycle_column_not_an_overwrite() -> None:
    source = _migration()
    assert "retired_at timestamptz" in source
    assert "retired_at IS NULL OR retired_at >= generated_at" in source
    # Identity rows are immutable apart from retirement. Scope this to the SQL: the
    # module docstring mentions ON CONFLICT precisely to contrast with the D0 table.
    sql = source[source.index("def upgrade():") :]
    assert "ON CONFLICT" not in sql
    producer_sql = PRODUCER.read_text(encoding="utf-8")
    assert "ON CONFLICT" not in producer_sql[producer_sql.index("async def produce_account_binding_identity") :]


# --- database-side immutability, not writer goodwill -------------------------
#
# The CHECK constraints reject non-canonical *values*. They do not stop a
# privileged writer replacing one canonical identifier with a different canonical
# identifier, so "the repository never overwrites" is a weaker claim than
# "the database refuses the overwrite". Only the second survives a compromised or
# buggy writer, which is the threat this authority exists to bound.


@pytest.mark.parametrize(
    "column",
    [
        "executor_id",
        "key_id",
        "scheme",
        "contract_version",
        "algorithm",
        "identifier",
        "binding_source",
        "broker_server",
        "generated_at",
        "producer_version",
    ],
)
def test_every_column_except_retirement_is_frozen_by_a_trigger(column: str) -> None:
    sql = _migration()[_migration().index("def upgrade():") :]
    guard = sql[sql.index("CREATE FUNCTION reject_account_binding_identity_mutation_v1") : sql.index("RETURN NEW")]
    assert f"NEW.{column}" in guard
    assert f"OLD.{column}" in guard


def test_the_immutability_guard_is_bound_as_a_before_update_trigger() -> None:
    sql = _migration()[_migration().index("def upgrade():") :]
    assert "CREATE TRIGGER trg_account_binding_identity_immutable_v1" in sql
    assert "BEFORE UPDATE ON executor_account_binding_identifiers" in sql
    assert "EXECUTE FUNCTION reject_account_binding_identity_mutation_v1()" in sql


def test_retirement_is_final_and_retired_at_is_the_only_writable_column() -> None:
    sql = _migration()[_migration().index("def upgrade():") :]
    guard = sql[sql.index("CREATE FUNCTION reject_account_binding_identity_mutation_v1") : sql.index("$immutable$;")]
    # retired_at is absent from the frozen-column list precisely because it is the
    # one supported mutation.
    frozen = guard[: guard.index("END IF;")]
    assert "NEW.retired_at" not in frozen
    assert "OLD.retired_at IS NOT NULL AND NEW.retired_at IS DISTINCT FROM OLD.retired_at" in guard


def test_deleting_an_executor_cannot_erase_its_identity_provenance() -> None:
    # Scope to the SQL: the docstring discusses the CASCADE on the D0 table by name.
    sql = _migration()[_migration().index("def upgrade():") :]
    assert "REFERENCES executor_instances(executor_id) ON DELETE RESTRICT" in sql
    assert "ON DELETE CASCADE" not in sql


def test_downgrade_removes_the_guard_it_installed() -> None:
    downgrade = _migration()[_migration().index("def downgrade():") :]
    assert "DROP TRIGGER trg_account_binding_identity_immutable_v1" in downgrade
    assert "DROP FUNCTION reject_account_binding_identity_mutation_v1()" in downgrade


# --- P4-C13 / P4-C14 / P4-C15 / P4-C16: audit projection --------------------


def test_audit_view_supports_shadow_and_demo_only() -> None:
    view = _migration()
    view = view[view.index("CREATE VIEW wolf15_audit.account_binding_identity_v1") :]
    assert "e.execution_mode IN ('SHADOW', 'DEMO')" in view
    assert "LIVE" not in view


def test_audit_view_excludes_revoked_and_retired() -> None:
    view = _migration()
    view = view[view.index("CREATE VIEW wolf15_audit.account_binding_identity_v1") :]
    assert "e.revoked_at IS NULL" in view
    assert "b.retired_at IS NULL" in view


def test_audit_view_does_not_hide_a_broker_server_disagreement() -> None:
    """P4-C24 at the projection boundary.

    Filtering ``e.broker_server = b.broker_server`` would hide a wrong-server
    identity from the auditor entirely and leave the reconciler unable to tell it
    apart from an absent one. The disagreement is surfaced and blocked instead.
    """

    view = _migration()
    view = view[view.index("CREATE VIEW wolf15_audit.account_binding_identity_v1") :]
    assert "e.broker_server = b.broker_server" not in view
    assert "b.broker_server" in view


def test_audit_view_is_security_barrier_and_hides_raw_account_fields() -> None:
    view = _migration()
    view = view[
        view.index("CREATE VIEW wolf15_audit.account_binding_identity_v1") : view.index(
            "REVOKE ALL ON wolf15_audit.account_binding_identity_v1"
        )
    ]
    assert "WITH (security_barrier=true)" in view
    for forbidden in ("account_id", "login_hash", "snapshot_payload"):
        assert forbidden not in view


def test_auditor_is_granted_the_view_and_denied_the_base_table() -> None:
    source = _migration()
    assert "GRANT SELECT ON wolf15_audit.account_binding_identity_v1 TO wolf15_auditor" in source
    assert "REVOKE ALL ON executor_account_binding_identifiers FROM wolf15_auditor" in source
    assert "REVOKE ALL ON executor_account_binding_identifiers FROM PUBLIC" in source


# --- P4-C19 / P4-C20: producer trust boundary --------------------------------


def test_producer_reads_identity_only_from_the_authoritative_table() -> None:
    producer = PRODUCER.read_text(encoding="utf-8")
    assert "FROM executor_instances WHERE executor_id=$1::uuid FOR UPDATE" in producer
    # Identity is derived, never accepted. No parameter may carry a login, server,
    # key id or identifier into this module.
    signature = producer[producer.index("async def produce_account_binding_identity") :]
    signature = signature[: signature.index(")")]
    assert "login" not in signature
    assert "server" not in signature
    assert "identifier" not in signature
    assert "key_id" not in signature


def test_producer_reuses_the_shared_primitive_and_does_not_reimplement_hmac() -> None:
    producer = PRODUCER.read_text(encoding="utf-8")
    assert "account_binding.identifier(" in producer
    for forbidden in ("hmac.new", "hashlib.sha256", "import hmac", "import hashlib"):
        assert forbidden not in producer


def test_producer_supports_shadow_and_demo_only() -> None:
    assert frozenset({"SHADOW", "DEMO"}) == identity_repo.SUPPORTED_EXECUTION_MODES
    assert "LIVE" not in identity_repo.SUPPORTED_EXECUTION_MODES


def test_producer_rejects_revoked_executor_and_unsupported_mode() -> None:
    producer = PRODUCER.read_text(encoding="utf-8")
    assert 'raise AccountBindingIdentityError("ACCOUNT_BINDING_EXECUTOR_REVOKED")' in producer
    assert 'raise AccountBindingIdentityError("ACCOUNT_BINDING_EXECUTION_MODE_UNSUPPORTED")' in producer


def test_producer_is_idempotent_and_fails_closed_on_reused_key_id() -> None:
    """P4-C21 / P4-C22 as a source contract; exercised against a server in integration."""

    producer = PRODUCER.read_text(encoding="utf-8")
    assert "identifiers_match(existing[" in producer
    assert 'raise AccountBindingIdentityError("ACCOUNT_BINDING_IDENTITY_CONFLICT")' in producer
    assert 'raise AccountBindingIdentityError("ACCOUNT_BINDING_IDENTITY_RETIRED")' in producer


def test_retirement_does_not_rewrite_an_identifier() -> None:
    producer = PRODUCER.read_text(encoding="utf-8")
    retire = producer[producer.index("async def retire_account_binding_identity") :]
    assert "SET retired_at = clock_timestamp()" in retire
    assert "SET identifier" not in retire
    assert "retired_at IS NULL" in retire


# --- P4-C23 to P4-C30: reconciler selection ---------------------------------


def test_matching_identity_at_the_direct_key_version_closes_account_binding() -> None:
    report = _report(account_identifier=DIRECT_IDENTIFIER, account_identifier_source=account_binding.DATABASE_SOURCE)
    assert report["ACCOUNT_BINDING_STATE"] == "MATCHED"
    evidence = report["account_binding_evidence"]
    assert evidence["direct_account_identifier_match"] is True
    assert evidence["active_account_identity_count"] == 1
    assert evidence["eligible_account_identity_count"] == 1
    assert evidence["database_identifier_source_trusted"] is True


def test_missing_database_identity_is_incomplete_never_matched() -> None:
    """P4-C25: absence must never read as agreement."""

    report = _report()
    assert report["ACCOUNT_BINDING_STATE"] == "INCOMPLETE_ACCOUNT_IDENTIFIER"
    assert report["B-B16"] != "EXECUTED_PASS"
    assert report["account_binding_evidence"]["active_account_identity_count"] == 0


def test_untrusted_binding_source_blocks() -> None:
    report = _report(account_identifier=DIRECT_IDENTIFIER, account_identifier_source="MANUAL_INPUT")
    assert report["ACCOUNT_BINDING_STATE"] == "UNTRUSTED_DATABASE_IDENTIFIER"
    assert report["B-B16"] == "EXECUTED_BLOCKED"
    assert report["account_binding_evidence"]["database_identifier_source_trusted"] is False


@pytest.mark.parametrize("field", ["scheme", "contract_version", "algorithm"])
def test_non_canonical_contract_metadata_blocks(field: str) -> None:
    rows = [
        _identity_row(
            identifier=DIRECT_IDENTIFIER,
            source=account_binding.DATABASE_SOURCE,
            **{field: "TAMPERED"},
        )
    ]
    report = _report(account_identity_rows=rows)
    assert report["ACCOUNT_BINDING_STATE"] == "UNTRUSTED_DATABASE_IDENTIFIER"
    assert report["B-B16"] == "EXECUTED_BLOCKED"


def test_malformed_identifier_blocks() -> None:
    rows = [_identity_row(identifier="not-a-w15ab-identifier", source=account_binding.DATABASE_SOURCE)]
    report = _report(account_identity_rows=rows)
    assert report["ACCOUNT_BINDING_STATE"] == "INVALID_DATABASE_IDENTIFIER"
    assert report["B-B16"] == "EXECUTED_BLOCKED"
    assert report["account_binding_evidence"]["database_identifier_contract_valid"] is False


def test_key_version_mismatch_blocks_without_falling_back() -> None:
    """P4-C23: an identity under another key version is not a substitute."""

    rows = [_identity_row(identifier=OTHER_IDENTIFIER, source=account_binding.DATABASE_SOURCE, key_id=OTHER_KEY_ID)]
    report = _report(account_identity_rows=rows)
    assert report["ACCOUNT_BINDING_STATE"] == "KEY_VERSION_MISMATCH"
    assert report["B-B16"] == "EXECUTED_BLOCKED"
    assert report["account_binding_evidence"]["eligible_account_identity_count"] == 0


def test_rotation_overlap_selects_only_the_direct_key_version() -> None:
    """P4-C29: two active keys is legitimate; only the presented one is eligible."""

    rows = [
        _identity_row(identifier=OTHER_IDENTIFIER, source=account_binding.DATABASE_SOURCE, key_id=OTHER_KEY_ID),
        _identity_row(identifier=DIRECT_IDENTIFIER, source=account_binding.DATABASE_SOURCE, key_id=TEST_KEY_ID),
    ]
    report = _report(account_identity_rows=rows)
    assert report["ACCOUNT_BINDING_STATE"] == "MATCHED"
    evidence = report["account_binding_evidence"]
    assert evidence["active_account_identity_count"] == 2
    assert evidence["eligible_account_identity_count"] == 1


def test_retired_identity_cannot_satisfy_account_binding() -> None:
    """P4-C12: retirement removes eligibility even for the correct identifier."""

    rows = [
        _identity_row(
            identifier=DIRECT_IDENTIFIER,
            source=account_binding.DATABASE_SOURCE,
            retired_at=(WINDOW_TO - timedelta(seconds=1)).isoformat(),
        )
    ]
    report = _report(account_identity_rows=rows)
    assert report["ACCOUNT_BINDING_STATE"] == "INCOMPLETE_ACCOUNT_IDENTIFIER"
    assert report["B-B16"] != "EXECUTED_PASS"


def test_duplicate_active_authority_for_one_key_blocks() -> None:
    """P4-C30: ambiguity is never resolved by picking one."""

    rows = [
        _identity_row(identifier=DIRECT_IDENTIFIER, source=account_binding.DATABASE_SOURCE),
        _identity_row(identifier=DIRECT_IDENTIFIER, source=account_binding.DATABASE_SOURCE),
    ]
    report = _report(account_identity_rows=rows)
    assert report["ACCOUNT_BINDING_STATE"] == "AMBIGUOUS_ACCOUNT_IDENTITY"
    assert report["B-B16"] == "EXECUTED_BLOCKED"
    assert report["account_binding_evidence"]["eligible_account_identity_count"] == 2


@pytest.mark.parametrize("server", ["broker-demo", "Broker-Demo2", "Broker-Demo "])
def test_exact_case_broker_server_mismatch_blocks(server: str) -> None:
    """P4-C24: a server disagreement blocks; it never reads as a missing identity.

    The regression this pins: filtering the server away during selection made
    "no identity exists" and "an identity exists for another server" produce the
    same INCOMPLETE state, which downgrades a hard binding failure to a soft gap.
    """

    rows = [
        _identity_row(
            identifier=DIRECT_IDENTIFIER,
            source=account_binding.DATABASE_SOURCE,
            broker_server=server,
        )
    ]
    report = _report(account_identity_rows=rows)
    assert report["ACCOUNT_BINDING_STATE"] == "BROKER_SERVER_MISMATCH"
    assert report["BROKER_RECONCILIATION"] == "ACCOUNT_IDENTITY_BROKER_SERVER_MISMATCH"
    assert report["B-B16"] == "EXECUTED_BLOCKED"
    evidence = report["account_binding_evidence"]
    assert evidence["account_identity_broker_server_matches"] is False
    # The identity was found and rejected, not missed.
    assert evidence["active_account_identity_count"] == 1
    assert evidence["eligible_account_identity_count"] == 1
    # The identifier is never compared once the server disagrees.
    assert evidence["direct_account_identifier_match"] == "NOT_MEASURED_NOT_EXPOSED_BY_AUDIT_VIEW"


def test_server_mismatch_is_distinguishable_from_a_missing_identity() -> None:
    """The two facts must not collapse onto one state."""

    absent = _report(account_identity_rows=[])
    wrong_server = _report(
        account_identity_rows=[
            _identity_row(
                identifier=DIRECT_IDENTIFIER,
                source=account_binding.DATABASE_SOURCE,
                broker_server="Broker-Other",
            )
        ]
    )
    assert absent["ACCOUNT_BINDING_STATE"] == "INCOMPLETE_ACCOUNT_IDENTIFIER"
    assert absent["B-B16"] == "EXECUTED_INCOMPLETE"
    assert wrong_server["ACCOUNT_BINDING_STATE"] == "BROKER_SERVER_MISMATCH"
    assert wrong_server["B-B16"] == "EXECUTED_BLOCKED"


def test_key_version_is_resolved_before_the_server_is_compared() -> None:
    """A wrong-server row under another key version is a key mismatch, not a server one."""

    rows = [
        _identity_row(
            identifier=OTHER_IDENTIFIER,
            source=account_binding.DATABASE_SOURCE,
            key_id=OTHER_KEY_ID,
            broker_server="Broker-Other",
        )
    ]
    report = _report(account_identity_rows=rows)
    assert report["ACCOUNT_BINDING_STATE"] == "KEY_VERSION_MISMATCH"
    assert report["B-B16"] == "EXECUTED_BLOCKED"


def test_different_account_identity_mismatches_rather_than_matching() -> None:
    other = account_binding.identifier(secret_key=b"k" * 32, key_id=TEST_KEY_ID, login="99999999", server="Broker-Demo")
    report = _report(account_identifier=other, account_identifier_source=account_binding.DATABASE_SOURCE)
    assert report["ACCOUNT_BINDING_STATE"] == "MISMATCH"
    assert report["B-B16"] == "EXECUTED_BLOCKED"


# --- authority separation ----------------------------------------------------


def test_legacy_binding_identifier_is_never_trusted_as_channel_b_identity() -> None:
    """The pre-P4 overlay is gone: a legacy identifier column cannot close B-B16."""

    database = _database()
    database["account_binding"][0]["account_binding_identifier"] = DIRECT_IDENTIFIER
    database["account_binding"][0]["account_binding_source"] = account_binding.DATABASE_SOURCE
    report = reconcile.reconcile_snapshots(
        database=database, broker=_broker(), window_from=WINDOW_FROM, window_to=WINDOW_TO
    )
    assert report["ACCOUNT_BINDING_STATE"] == "INCOMPLETE_ACCOUNT_IDENTIFIER"
    assert report["B-B16"] != "EXECUTED_PASS"


def test_reconciler_no_longer_overlays_backend_identity_onto_legacy_rows() -> None:
    source = (ROOT / "ops" / "mt5_mcp" / "reconcile.py").read_text(encoding="utf-8")
    assert "Replace any legacy identifier columns" not in source
    assert '"account_binding_identifier": projected' not in source
    assert "BINDING_IDENTITY_SQL" in source
    assert "wolf15_audit.account_binding_identity_v1" in source


def test_d0_reconciliation_evidence_object_is_left_intact() -> None:
    """P4 adds an authority; it does not delete or repurpose the D0 prototype."""

    d0_migration = (VERSIONS / "20260910_02_reconciliation_evidence.py").read_text(encoding="utf-8")
    assert "CREATE TABLE executor_reconciliation_bindings" in d0_migration
    assert "backend_account_identity_v1" in d0_migration
    assert "DROP TABLE executor_reconciliation_bindings" not in _migration()
    assert "backend_account_identity_v1" not in _migration()


def test_identity_rows_are_measured_separately_from_legacy_rows() -> None:
    report = _report(account_identifier=DIRECT_IDENTIFIER, account_identifier_source=account_binding.DATABASE_SOURCE)
    measurements = report["database_measurements"]
    assert measurements["account_binding_rows"] == 1
    assert measurements["account_binding_identity_rows"] == 1
