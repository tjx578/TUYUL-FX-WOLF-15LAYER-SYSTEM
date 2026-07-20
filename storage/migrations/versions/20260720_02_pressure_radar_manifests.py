"""Add durable pressure-radar manifests and deployment-scoped event dedup.

Revision ID: 20260720_02
Revises: 20260720_01

The manifest latches a provisional pressure qualification until canonical
clean-block lineage arrives.  It is analysis-only and may reference a pressure
outbox event only after the manifest reaches ``ANALYSIS_READY``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine.reflection import Inspector

revision = "20260720_02"
down_revision = "20260720_01"
branch_labels = None
depends_on = None


def _index_names(inspector: Inspector, table_name: str) -> set[str]:
    return {str(item["name"]) for item in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("pressure_radar_manifests"):
        op.create_table(
            "pressure_radar_manifests",
            sa.Column("manifest_id", sa.Text(), primary_key=True),
            sa.Column("deployment_id", sa.String(200), nullable=False),
            sa.Column("gate_rule_version", sa.String(100), nullable=False),
            sa.Column("symbol", sa.String(32), nullable=False),
            sa.Column("raw_direction", sa.String(4), nullable=False),
            sa.Column("context_signature", sa.String(71), nullable=False),
            sa.Column("qualifying_time_utc", sa.DateTime(timezone=True), nullable=False),
            sa.Column("raw_direction_expires_at_utc", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(48), nullable=False),
            sa.Column("manifest", JSONB(), nullable=False),
            sa.Column("qualifying_payload", JSONB(), nullable=False),
            sa.Column(
                "outbox_event_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("pressure_outbox.event_id", ondelete="RESTRICT"),
                nullable=True,
                unique=True,
            ),
            sa.Column(
                "outbox_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("pressure_outbox.id", ondelete="RESTRICT"),
                nullable=True,
                unique=True,
            ),
            sa.Column("revision", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.CheckConstraint("raw_direction IN ('BUY', 'SELL')", name="ck_pressure_radar_direction"),
            sa.CheckConstraint(
                "status IN ('WAITING_CANONICAL_LINEAGE', 'ANALYSIS_READY', 'EXPIRED', "
                "'INVALIDATED_DIRECTION_REVERSAL', 'CANCELLED')",
                name="ck_pressure_radar_manifest_status",
            ),
            sa.CheckConstraint("revision > 0", name="ck_pressure_radar_revision_positive"),
            sa.CheckConstraint(
                "manifest ->> 'final_direction' = 'WAIT' "
                "AND (manifest ->> 'valid_for_execution')::boolean IS FALSE "
                "AND (manifest ->> 'is_final_signal')::boolean IS FALSE",
                name="ck_pressure_radar_non_executable",
            ),
            sa.CheckConstraint(
                "(status <> 'ANALYSIS_READY' OR (outbox_event_id IS NOT NULL AND outbox_id IS NOT NULL)) "
                "AND ((outbox_event_id IS NULL AND outbox_id IS NULL) "
                "OR (outbox_event_id IS NOT NULL AND outbox_id IS NOT NULL))",
                name="ck_pressure_radar_ready_outbox",
            ),
        )

    inspector = inspect(bind)
    manifest_indexes = _index_names(inspector, "pressure_radar_manifests")
    if "ix_pressure_radar_manifest_active" not in manifest_indexes:
        op.create_index(
            "ix_pressure_radar_manifest_active",
            "pressure_radar_manifests",
            ["deployment_id", "symbol", "qualifying_time_utc"],
            postgresql_where=sa.text("status IN ('WAITING_CANONICAL_LINEAGE', 'ANALYSIS_READY')"),
        )
    if "ix_pressure_radar_manifest_expiry" not in manifest_indexes:
        op.create_index(
            "ix_pressure_radar_manifest_expiry",
            "pressure_radar_manifests",
            ["status", "raw_direction_expires_at_utc"],
        )

    if not inspector.has_table("pressure_radar_events"):
        op.create_table(
            "pressure_radar_events",
            sa.Column("deployment_id", sa.String(200), nullable=False),
            sa.Column("event_id", sa.Text(), nullable=False),
            sa.Column("symbol", sa.String(32), nullable=False),
            sa.Column("observed_at_utc", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload_hash", sa.String(64), nullable=False),
            sa.Column("payload", JSONB(), nullable=False),
            sa.Column("transition", sa.String(64), nullable=False),
            sa.Column(
                "manifest_id",
                sa.Text(),
                sa.ForeignKey("pressure_radar_manifests.manifest_id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "outbox_event_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("pressure_outbox.event_id", ondelete="RESTRICT"),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("deployment_id", "event_id", name="pk_pressure_radar_events"),
        )

    inspector = inspect(bind)
    event_indexes = _index_names(inspector, "pressure_radar_events")
    if "ix_pressure_radar_event_manifest" not in event_indexes:
        op.create_index(
            "ix_pressure_radar_event_manifest",
            "pressure_radar_events",
            ["manifest_id", "observed_at_utc"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("pressure_radar_events"):
        event_indexes = _index_names(inspector, "pressure_radar_events")
        if "ix_pressure_radar_event_manifest" in event_indexes:
            op.drop_index("ix_pressure_radar_event_manifest", table_name="pressure_radar_events")
        op.drop_table("pressure_radar_events")

    inspector = inspect(bind)
    if inspector.has_table("pressure_radar_manifests"):
        manifest_indexes = _index_names(inspector, "pressure_radar_manifests")
        for index_name in (
            "ix_pressure_radar_manifest_expiry",
            "ix_pressure_radar_manifest_active",
        ):
            if index_name in manifest_indexes:
                op.drop_index(index_name, table_name="pressure_radar_manifests")
        op.drop_table("pressure_radar_manifests")
