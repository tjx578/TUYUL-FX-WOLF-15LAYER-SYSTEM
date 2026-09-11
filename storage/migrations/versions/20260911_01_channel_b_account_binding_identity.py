"""Durable Channel-B account-binding identity authority.

This is deliberately NOT the D0 object from 20260910_02.
``executor_reconciliation_bindings`` is snapshot-coupled, DEMO-only, and keyed by
``executor_id`` alone with ``ON CONFLICT DO UPDATE``, so an identifier is rewritten
in place when a binding changes. That is correct as one-shot D0 reconciliation
evidence and wrong as a durable identity authority: it cannot express a bounded
key-rotation overlap, and it cannot prove identity for an executor still in
read-only SHADOW.

This table is keyed by ``(executor_id, key_id)`` so an old and a new key can be
active at the same time, and retirement is an explicit lifecycle mutation rather
than an overwrite.

Immutability is enforced by the server, not by the writer's goodwill. The CHECK
constraints only reject non-canonical *values*; a privileged writer could still
replace one canonical identifier with a different canonical identifier. A BEFORE
UPDATE trigger therefore rejects every column change except ``NULL -> timestamp``
on ``retired_at``, and retirement is final. The foreign key is ``ON DELETE
RESTRICT`` for the same reason: deleting an executor must not silently erase the
identity provenance bound to it.

The audit projection deliberately does NOT filter on
``e.broker_server = b.broker_server``. Hiding a row whose bound server disagrees
with the executor's registered server would make "identity absent" and "identity
present under the wrong server" indistinguishable to both the auditor and the
reconciler, and the second case must block rather than read as incomplete.

It stores only the opaque identifier and public metadata. No HMAC secret, no
``account_id``, no ``login_hash``, no login suffix, no credential material, and no
free-form diagnostic payload ever reaches PostgreSQL through this path.

Revision ID: 20260911_01
Revises: 20260910_02
"""

from alembic import op

revision = "20260911_01"
down_revision = "20260910_02"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE executor_account_binding_identifiers (
            executor_id uuid NOT NULL REFERENCES executor_instances(executor_id) ON DELETE RESTRICT,
            key_id varchar(32) NOT NULL,
            scheme text NOT NULL,
            contract_version text NOT NULL,
            algorithm text NOT NULL,
            identifier text NOT NULL,
            binding_source text NOT NULL,
            broker_server varchar(200) NOT NULL,
            generated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            retired_at timestamptz,
            producer_version varchar(64) NOT NULL,
            PRIMARY KEY (executor_id, key_id),
            CONSTRAINT account_binding_identity_scheme
                CHECK (scheme = 'w15-account-binding'),
            CONSTRAINT account_binding_identity_version
                CHECK (contract_version = 'v1'),
            CONSTRAINT account_binding_identity_algorithm
                CHECK (algorithm = 'HMAC-SHA-256'),
            CONSTRAINT account_binding_identity_source
                CHECK (binding_source = 'EXECUTOR_INSTANCE_ACCOUNT_ID'),
            CONSTRAINT account_binding_identity_key_id_shape
                CHECK (key_id ~ '^[a-z0-9][a-z0-9._-]{0,31}$'),
            CONSTRAINT account_binding_identity_shape
                CHECK (identifier ~ '^w15ab:v1:[a-z0-9][a-z0-9._-]{0,31}:[A-Za-z0-9_-]{43}$'),
            CONSTRAINT account_binding_identity_key_id_agrees
                CHECK (split_part(identifier, ':', 3) = key_id),
            CONSTRAINT account_binding_identity_retirement_order
                CHECK (retired_at IS NULL OR retired_at >= generated_at)
        );
        CREATE INDEX ix_account_binding_identity_active
            ON executor_account_binding_identifiers(executor_id, broker_server)
            WHERE retired_at IS NULL;
        REVOKE ALL ON executor_account_binding_identifiers FROM PUBLIC;
        CREATE SCHEMA IF NOT EXISTS wolf15_audit;
        CREATE VIEW wolf15_audit.account_binding_identity_v1 WITH (security_barrier=true) AS
            SELECT b.executor_id,
                   b.broker_server,
                   e.execution_mode,
                   b.key_id,
                   b.scheme,
                   b.contract_version,
                   b.algorithm,
                   b.identifier,
                   b.binding_source,
                   b.generated_at,
                   b.retired_at,
                   b.producer_version
              FROM executor_account_binding_identifiers b
              JOIN executor_instances e ON e.executor_id = b.executor_id
             WHERE e.execution_mode IN ('SHADOW', 'DEMO')
               AND e.revoked_at IS NULL
               AND b.retired_at IS NULL;
        REVOKE ALL ON wolf15_audit.account_binding_identity_v1 FROM PUBLIC;
        CREATE FUNCTION reject_account_binding_identity_mutation_v1()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $immutable$
        BEGIN
            IF NEW.executor_id      IS DISTINCT FROM OLD.executor_id
            OR NEW.key_id           IS DISTINCT FROM OLD.key_id
            OR NEW.scheme           IS DISTINCT FROM OLD.scheme
            OR NEW.contract_version IS DISTINCT FROM OLD.contract_version
            OR NEW.algorithm        IS DISTINCT FROM OLD.algorithm
            OR NEW.identifier       IS DISTINCT FROM OLD.identifier
            OR NEW.binding_source   IS DISTINCT FROM OLD.binding_source
            OR NEW.broker_server    IS DISTINCT FROM OLD.broker_server
            OR NEW.generated_at     IS DISTINCT FROM OLD.generated_at
            OR NEW.producer_version IS DISTINCT FROM OLD.producer_version THEN
                RAISE EXCEPTION 'account binding identity is immutable; retirement is the only supported mutation'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_account_binding_identity_immutable_v1';
            END IF;
            IF OLD.retired_at IS NOT NULL AND NEW.retired_at IS DISTINCT FROM OLD.retired_at THEN
                RAISE EXCEPTION 'account binding identity retirement is final'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_account_binding_identity_retirement_final_v1';
            END IF;
            RETURN NEW;
        END
        $immutable$;
        CREATE TRIGGER trg_account_binding_identity_immutable_v1
            BEFORE UPDATE ON executor_account_binding_identifiers
            FOR EACH ROW
            EXECUTE FUNCTION reject_account_binding_identity_mutation_v1();
        DO $grant$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='wolf15_auditor') THEN
                GRANT USAGE ON SCHEMA wolf15_audit TO wolf15_auditor;
                GRANT SELECT ON wolf15_audit.account_binding_identity_v1 TO wolf15_auditor;
                REVOKE ALL ON executor_account_binding_identifiers FROM wolf15_auditor;
            END IF;
        END $grant$;
    """)


def downgrade():
    op.execute("""
        DROP VIEW wolf15_audit.account_binding_identity_v1;
        DROP TRIGGER trg_account_binding_identity_immutable_v1
            ON executor_account_binding_identifiers;
        DROP TABLE executor_account_binding_identifiers;
        DROP FUNCTION reject_account_binding_identity_mutation_v1();
    """)
