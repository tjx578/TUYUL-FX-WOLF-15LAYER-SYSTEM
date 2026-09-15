"""Join D1 admission/control capabilities with the current account identity lineage.

Revision ID: 20260915_01
Revises: 20260908_01, 20260911_01

Both published histories are retained. This merge adds no DDL or authority.
"""

revision = "20260915_01"
down_revision = ("20260908_01", "20260911_01")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
