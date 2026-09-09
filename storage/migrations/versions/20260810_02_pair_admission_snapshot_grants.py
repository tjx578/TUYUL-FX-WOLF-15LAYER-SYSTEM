"""Separate PairAdmission evaluation snapshots from logical grant creation.

Revision ID: 20260810_02
Revises: 20260810_01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260810_02"
down_revision = "20260810_01"
branch_labels = None
depends_on = None

_TABLE = "pair_admission_evaluations"
_COLUMN = "logical_grant_created"
_CHECK = "ck_pair_admission_logical_grant_shape"
_INDEX = "uq_pair_admission_one_grant_per_block"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {str(item["name"]) for item in inspector.get_columns(_TABLE)}
    if _COLUMN not in columns:
        op.add_column(
            _TABLE,
            sa.Column(_COLUMN, sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.execute(
            sa.text("UPDATE pair_admission_evaluations SET logical_grant_created = TRUE WHERE decision = 'GRANTED'")
        )

    inspector = inspect(bind)
    constraints = {str(item["name"]) for item in inspector.get_check_constraints(_TABLE)}
    if _CHECK not in constraints:
        op.create_check_constraint(
            _CHECK,
            _TABLE,
            "logical_grant_created IS FALSE OR decision = 'GRANTED'",
        )

    indexes = {str(item["name"]) for item in inspector.get_indexes(_TABLE)}
    if _INDEX in indexes:
        op.drop_index(_INDEX, table_name=_TABLE)
    op.create_index(
        _INDEX,
        _TABLE,
        ["deployment_id", "raw_block_id", "rule_version"],
        unique=True,
        postgresql_where=sa.text("logical_grant_created IS TRUE"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    duplicate_grants = bind.execute(
        sa.text(
            "SELECT 1 FROM pair_admission_evaluations "
            "WHERE decision = 'GRANTED' AND logical_grant_created IS FALSE LIMIT 1"
        )
    ).first()
    if duplicate_grants is not None:
        raise RuntimeError(
            "cannot downgrade 20260810_02 after versioned GRANTED snapshots exist; "
            "downgrade would discard immutable audit evidence"
        )

    op.drop_index(_INDEX, table_name=_TABLE)
    op.create_index(
        _INDEX,
        _TABLE,
        ["deployment_id", "raw_block_id", "rule_version"],
        unique=True,
        postgresql_where=sa.text("decision = 'GRANTED'"),
    )
    op.drop_constraint(_CHECK, _TABLE, type_="check")
    op.drop_column(_TABLE, _COLUMN)
