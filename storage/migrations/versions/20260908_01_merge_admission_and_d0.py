"""Join the independently published admission and D0 migration histories.

Revision ID: 20260908_01
Revises: 20260826_01, 20260905_01

Both parent branches retain their original identities. Alembic must apply the
missing parent before recording this merge; this revision changes no data,
privileges, or execution authority.
"""

from __future__ import annotations

revision = "20260908_01"
down_revision = ("20260826_01", "20260905_01")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
