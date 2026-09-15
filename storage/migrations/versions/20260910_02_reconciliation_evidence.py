"""Backend-derived account identity and authenticated D0 reconciliation evidence.

Revision ID: 20260910_02
Revises: 20260910_01
"""

from alembic import op

revision = "20260910_02"
down_revision = "20260910_01"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE executor_reconciliation_bindings (
            executor_id uuid PRIMARY KEY REFERENCES executor_instances(executor_id) ON DELETE CASCADE,
            binding_version uuid NOT NULL UNIQUE,
            account_id varchar(100) NOT NULL,
            login_hash varchar(80) NOT NULL,
            broker_server varchar(200) NOT NULL,
            account_binding_identifier text NOT NULL,
            snapshot_id varchar(200) NOT NULL,
            snapshot_sha256 varchar(64) NOT NULL,
            snapshot_payload jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE TABLE broker_reconciliation_evidence (
            evidence_id uuid PRIMARY KEY,
            executor_id uuid NOT NULL REFERENCES executor_instances(executor_id) ON DELETE CASCADE,
            binding_version uuid NOT NULL,
            snapshot_id varchar(200) NOT NULL,
            payload jsonb NOT NULL,
            payload_sha256 varchar(64) NOT NULL,
            status text NOT NULL CHECK (status IN ('ACTIVE', 'REVOKED')),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE INDEX ix_reconciliation_executor_snapshot
            ON broker_reconciliation_evidence(executor_id, snapshot_id, created_at DESC);
        REVOKE ALL ON executor_reconciliation_bindings, broker_reconciliation_evidence FROM PUBLIC;
        CREATE SCHEMA IF NOT EXISTS wolf15_audit;
        CREATE VIEW wolf15_audit.backend_account_identity_v1 WITH (security_barrier=true) AS
            SELECT b.executor_id, b.binding_version, b.broker_server, b.account_binding_identifier,
                   'EXECUTOR_INSTANCE_ACCOUNT_ID'::text AS account_binding_source,
                   b.snapshot_id, b.snapshot_sha256
            FROM executor_reconciliation_bindings b
            JOIN executor_instances e ON e.executor_id=b.executor_id
            JOIN executor_account_snapshots s ON s.snapshot_id=b.snapshot_id AND s.executor_id=e.executor_id
            WHERE e.account_id=b.account_id AND e.login_hash=b.login_hash
              AND e.broker_server=b.broker_server AND e.execution_mode='DEMO' AND e.revoked_at IS NULL
              AND s.account_id=e.account_id AND s.payload=b.snapshot_payload;
        REVOKE ALL ON wolf15_audit.backend_account_identity_v1 FROM PUBLIC;
        DO $grant$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='wolf15_auditor') THEN
                GRANT USAGE ON SCHEMA wolf15_audit TO wolf15_auditor;
                GRANT SELECT ON wolf15_audit.backend_account_identity_v1 TO wolf15_auditor;
                REVOKE ALL ON executor_reconciliation_bindings, broker_reconciliation_evidence FROM wolf15_auditor;
            END IF;
        END $grant$;
    """)


def downgrade():
    op.execute("""
        DROP VIEW wolf15_audit.backend_account_identity_v1;
        DROP TABLE broker_reconciliation_evidence;
        DROP TABLE executor_reconciliation_bindings;
    """)
