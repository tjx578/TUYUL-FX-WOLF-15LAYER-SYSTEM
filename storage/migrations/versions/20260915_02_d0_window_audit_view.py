"""Expose only aggregate D0 window counts to the read-only auditor.

Revision ID: 20260915_02
Revises: 20260915_01
"""

from alembic import op

revision = "20260915_02"
down_revision = "20260915_01"
branch_labels = None
depends_on = None

WINDOW_COUNTS_SQL = """
    SELECT count(*) AS open_window_count,
           count(*) FILTER (WHERE state = 'QUEUED') AS queued_count,
           count(*) FILTER (WHERE state = 'ARMED') AS armed_count,
           count(*) FILTER (WHERE state = 'RECONCILIATION_REQUIRED')
               AS reconciliation_required_count
      FROM public.engineering_demo_canary_windows
     WHERE state IN ('QUEUED', 'ARMED', 'RECONCILIATION_REQUIRED')
"""


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS wolf15_audit")
    op.execute("CREATE VIEW wolf15_audit.d0_window_counts_v1 WITH (security_barrier=true) AS " + WINDOW_COUNTS_SQL)
    op.execute("REVOKE ALL ON wolf15_audit.d0_window_counts_v1 FROM PUBLIC")
    op.execute("""
        DO $grant$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wolf15_auditor') THEN
                GRANT USAGE ON SCHEMA wolf15_audit TO wolf15_auditor;
                GRANT SELECT ON wolf15_audit.d0_window_counts_v1 TO wolf15_auditor;
            END IF;
        END $grant$;
    """)


def downgrade() -> None:
    op.execute("DROP VIEW wolf15_audit.d0_window_counts_v1")
