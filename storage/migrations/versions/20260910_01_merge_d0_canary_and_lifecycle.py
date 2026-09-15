"""Merge the D0 canary and lifecycle migration branches.

Revision ID: 20260910_01
Revises: 20260823_01, 20260909_07
"""

revision = "20260910_01"
down_revision = ("20260823_01", "20260909_07")
branch_labels = None
depends_on = None


def upgrade():
    """Join the already-applied schema branches without changing schema state."""


def downgrade():
    """Split the migration graph without changing schema state."""
