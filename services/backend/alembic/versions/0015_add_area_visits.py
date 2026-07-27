"""Add AreaVisit persistence tables.

Revision ID: 0015_area_visits
Revises: 0014_story_photo_projections
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015_area_visits"
down_revision: str | None = "0014_story_photo_projections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RECONSTRUCTION_SOURCE_VALUES = "'automation', 'user_correction', 'manual'"


def upgrade() -> None:
    op.create_table(
        "area_visits",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trip_day_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("place_id", postgresql.UUID(as_uuid=True)),
        sa.Column("title", sa.String(length=255)),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("starts_at_utc", sa.DateTime(timezone=True)),
        sa.Column("ends_at_utc", sa.DateTime(timezone=True)),
        sa.Column("center", sa.Text()),
        sa.Column(
            "bounds",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("cover_media_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "diagnostics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("algorithm_version", sa.String(length=80), nullable=False),
        sa.Column("reconstruction_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_locked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(f"source IN ({RECONSTRUCTION_SOURCE_VALUES})", name="source"),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence",
        ),
        sa.CheckConstraint("sort_order > 0", name="sort_order_positive"),
        sa.CheckConstraint(
            "ends_at_utc IS NULL OR starts_at_utc IS NULL OR ends_at_utc >= starts_at_utc",
            name="time_order",
        ),
        sa.ForeignKeyConstraint(["cover_media_id"], ["media_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["place_id"], ["places.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["reconstruction_run_id"], ["reconstruction_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["trip_day_id"], ["trip_days.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trip_day_id", "sort_order", "reconstruction_run_id"),
    )
    op.execute(
        "ALTER TABLE area_visits ALTER COLUMN center TYPE geography(Point,4326) "
        "USING center::geography"
    )
    op.create_index("ix_area_visits_trip_day_id", "area_visits", ["trip_day_id"])
    op.create_index(
        "ix_area_visits_trip_run",
        "area_visits",
        ["trip_id", "reconstruction_run_id"],
    )
    op.create_index(
        "ix_area_visits_center_gist",
        "area_visits",
        ["center"],
        postgresql_using="gist",
    )

    op.create_table(
        "area_visit_stops",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("area_visit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stop_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reconstruction_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("membership_source", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("algorithm_version", sa.String(length=80), nullable=False),
        sa.Column("user_locked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"membership_source IN ({RECONSTRUCTION_SOURCE_VALUES})",
            name="source",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence",
        ),
        sa.CheckConstraint("sort_order > 0", name="sort_order_positive"),
        sa.ForeignKeyConstraint(["area_visit_id"], ["area_visits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["reconstruction_run_id"], ["reconstruction_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["stop_id"], ["stops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("area_visit_id", "stop_id"),
        sa.UniqueConstraint("reconstruction_run_id", "stop_id"),
    )
    op.create_index(
        "ix_area_visit_stops_area_visit_id",
        "area_visit_stops",
        ["area_visit_id"],
    )
    op.create_index("ix_area_visit_stops_stop_id", "area_visit_stops", ["stop_id"])
    op.create_index(
        "ix_area_visit_stops_trip_run",
        "area_visit_stops",
        ["trip_id", "reconstruction_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_area_visit_stops_trip_run", table_name="area_visit_stops")
    op.drop_index("ix_area_visit_stops_stop_id", table_name="area_visit_stops")
    op.drop_index("ix_area_visit_stops_area_visit_id", table_name="area_visit_stops")
    op.drop_table("area_visit_stops")
    op.drop_index("ix_area_visits_center_gist", table_name="area_visits")
    op.drop_index("ix_area_visits_trip_run", table_name="area_visits")
    op.drop_index("ix_area_visits_trip_day_id", table_name="area_visits")
    op.drop_table("area_visits")
