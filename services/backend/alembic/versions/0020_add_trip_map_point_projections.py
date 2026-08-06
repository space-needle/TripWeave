"""Add trip map point projections.

Revision ID: 0020_trip_map_point_projections
Revises: 0019_area_visit_create
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0020_trip_map_point_projections"
down_revision: str | None = "0019_area_visit_create"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trip_map_point_projections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True)),
        sa.Column("captured_date", sa.Date()),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("filename", sa.Text()),
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
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence",
        ),
        sa.ForeignKeyConstraint(["media_item_id"], ["media_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("media_item_id"),
    )
    op.create_index(
        "ix_trip_map_point_projections_trip_id",
        "trip_map_point_projections",
        ["trip_id"],
    )
    op.create_index(
        "ix_trip_map_point_projections_trip_date",
        "trip_map_point_projections",
        ["trip_id", "captured_date"],
    )
    op.execute(
        """
        INSERT INTO trip_map_point_projections (
            trip_id,
            media_item_id,
            captured_at,
            captured_date,
            latitude,
            longitude,
            source,
            confidence,
            filename
        )
        SELECT
            media_items.trip_id,
            media_items.id,
            COALESCE(
                media_items.effective_captured_at_utc,
                media_items.original_captured_at_utc
            ) AS captured_at,
            COALESCE(
                media_items.effective_captured_at_utc,
                media_items.original_captured_at_utc
            )::date AS captured_date,
            ST_Y(media_items.effective_location::geometry) AS latitude,
            ST_X(media_items.effective_location::geometry) AS longitude,
            media_items.location_source,
            media_items.location_confidence,
            media_items.original_filename
        FROM media_items
        WHERE
            media_items.deleted_at IS NULL
            AND media_items.effective_location IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_trip_map_point_projections_trip_date",
        table_name="trip_map_point_projections",
    )
    op.drop_index(
        "ix_trip_map_point_projections_trip_id",
        table_name="trip_map_point_projections",
    )
    op.drop_table("trip_map_point_projections")
