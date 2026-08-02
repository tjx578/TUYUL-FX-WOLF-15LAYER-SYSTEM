"""Freeze signed MT5 command wire bytes for executor-side verification.

Revision ID: 20260803_01
Revises: 20260801_01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260803_01"
down_revision = "20260801_01"
branch_labels = None
depends_on = None

_LEGACY_WIRE = "legacy-json-v1"
_SIGNED_WIRE = "wolf15.mt5.exec.signed-bytes.v2"


def upgrade() -> None:
    op.add_column("execution_commands", sa.Column("wire_format", sa.String(length=50), nullable=True))
    op.add_column("execution_commands", sa.Column("payload_encoding", sa.String(length=20), nullable=True))
    op.add_column("execution_commands", sa.Column("signed_payload_b64", sa.Text(), nullable=True))
    op.add_column("execution_commands", sa.Column("signed_payload_sha256", sa.String(length=80), nullable=True))
    op.add_column("execution_commands", sa.Column("signature_algorithm", sa.String(length=32), nullable=True))
    op.add_column("execution_commands", sa.Column("signature_key_id", sa.String(length=100), nullable=True))
    op.add_column("execution_commands", sa.Column("signature_value", sa.String(length=80), nullable=True))

    # Existing records predate the immutable envelope and remain explicitly
    # identifiable. New inserts default to v2 and must satisfy the full CHECK.
    op.execute(
        sa.text("UPDATE execution_commands SET wire_format = :legacy WHERE wire_format IS NULL").bindparams(
            legacy=_LEGACY_WIRE
        )
    )
    op.alter_column(
        "execution_commands",
        "wire_format",
        nullable=False,
        server_default=sa.text(f"'{_SIGNED_WIRE}'"),
    )
    op.create_check_constraint(
        "ck_execution_command_signed_wire_complete",
        "execution_commands",
        f"""
        (
            wire_format = '{_LEGACY_WIRE}'
            AND payload_encoding IS NULL
            AND signed_payload_b64 IS NULL
            AND signed_payload_sha256 IS NULL
            AND signature_algorithm IS NULL
            AND signature_key_id IS NULL
            AND signature_value IS NULL
        )
        OR
        (
            wire_format = '{_SIGNED_WIRE}'
            AND payload_encoding IS NOT NULL
            AND payload_encoding = 'base64url'
            AND signed_payload_b64 IS NOT NULL
            AND signed_payload_b64 ~ '^[A-Za-z0-9_-]+$'
            AND signed_payload_sha256 IS NOT NULL
            AND signed_payload_sha256 = payload_hash
            AND signed_payload_sha256 ~ '^sha256:[0-9a-f]{{64}}$'
            AND signature_algorithm IS NOT NULL
            AND signature_algorithm = 'HMAC-SHA256'
            AND signature_key_id IS NOT NULL
            AND signature_key_id ~ '^[A-Za-z0-9._:-]{{1,100}}$'
            AND signature_value IS NOT NULL
            AND signature_value ~ '^base64url:[A-Za-z0-9_-]{{43}}$'
        )
        """,
    )
    op.execute(
        """
        CREATE FUNCTION reject_new_legacy_execution_command()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.wire_format = 'legacy-json-v1' THEN
                RAISE EXCEPTION 'new execution commands require signed wire v2'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_execution_command_signed_wire_new_rows';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_execution_command_require_signed_wire
        BEFORE INSERT ON execution_commands
        FOR EACH ROW EXECUTE FUNCTION reject_new_legacy_execution_command()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_execution_command_require_signed_wire ON execution_commands")
    op.execute("DROP FUNCTION IF EXISTS reject_new_legacy_execution_command()")
    op.drop_constraint(
        "ck_execution_command_signed_wire_complete",
        "execution_commands",
        type_="check",
    )
    op.drop_column("execution_commands", "signature_value")
    op.drop_column("execution_commands", "signature_key_id")
    op.drop_column("execution_commands", "signature_algorithm")
    op.drop_column("execution_commands", "signed_payload_sha256")
    op.drop_column("execution_commands", "signed_payload_b64")
    op.drop_column("execution_commands", "payload_encoding")
    op.drop_column("execution_commands", "wire_format")
