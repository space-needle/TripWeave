"""Add collaborative trip reconstruction tables.

Revision ID: 0007_reconstruction
Revises: 0006_guest_invitations
Create Date: 2026-07-13
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007_reconstruction"
down_revision = "0006_guest_invitations"
branch_labels = None
depends_on = None


def generated_columns() -> list[sa.Column]:
    return [
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
    ]


def generated_constraints(table_name: str) -> list[sa.Constraint]:
    return [
        sa.CheckConstraint(
            "source IN ('automation', 'user_correction', 'manual')",
            name=op.f(f"ck_{table_name}_source"),
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f(f"ck_{table_name}_confidence"),
        ),
        sa.ForeignKeyConstraint(
            ["reconstruction_run_id"],
            ["reconstruction_runs.id"],
            name=op.f(f"fk_{table_name}_reconstruction_run_id_reconstruction_runs"),
            ondelete="CASCADE",
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "reconstruction_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "state", sa.String(length=40), server_default=sa.text("'running'"), nullable=False
        ),
        sa.Column(
            "source", sa.String(length=40), server_default=sa.text("'automation'"), nullable=False
        ),
        sa.Column("confidence", sa.Float()),
        sa.Column("algorithm_version", sa.String(length=80), nullable=False),
        sa.Column("algorithm_config", postgresql.JSONB(), nullable=False),
        sa.Column("user_locked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "summary", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
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
            "state IN ('running', 'succeeded', 'failed')", name=op.f("ck_reconstruction_runs_state")
        ),
        sa.CheckConstraint(
            "source IN ('automation', 'user_correction', 'manual')",
            name=op.f("ck_reconstruction_runs_source"),
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_reconstruction_runs_confidence"),
        ),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_reconstruction_runs_trip_id"), "reconstruction_runs", ["trip_id"])

    op.create_table(
        "trip_days",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("day_date", sa.Date(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("starts_at_utc", sa.DateTime(timezone=True)),
        sa.Column("ends_at_utc", sa.DateTime(timezone=True)),
        *generated_columns(),
        *generated_constraints("trip_days"),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trip_id", "day_date", "reconstruction_run_id"),
    )
    op.create_index(op.f("ix_trip_days_trip_id"), "trip_days", ["trip_id"])

    op.create_table(
        "places",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255)),
        sa.Column("centroid", sa.Text()),
        *generated_columns(),
        *generated_constraints("places"),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "ALTER TABLE places ALTER COLUMN centroid TYPE geography(Point,4326) "
        "USING centroid::geography"
    )
    op.create_index(op.f("ix_places_trip_id"), "places", ["trip_id"])
    op.create_index("ix_places_centroid_gist", "places", ["centroid"], postgresql_using="gist")

    op.create_table(
        "stops",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trip_day_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("place_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("starts_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("centroid", sa.Text()),
        *generated_columns(),
        *generated_constraints("stops"),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trip_day_id"], ["trip_days.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["place_id"], ["places.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "ALTER TABLE stops ALTER COLUMN centroid TYPE geography(Point,4326) "
        "USING centroid::geography"
    )
    op.create_index(op.f("ix_stops_trip_id"), "stops", ["trip_id"])
    op.create_index(op.f("ix_stops_trip_day_id"), "stops", ["trip_day_id"])
    op.create_index("ix_stops_centroid_gist", "stops", ["centroid"], postgresql_using="gist")

    op.create_table(
        "moments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stop_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("starts_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at_utc", sa.DateTime(timezone=True), nullable=False),
        *generated_columns(),
        *generated_constraints("moments"),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stop_id"], ["stops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_moments_trip_id"), "moments", ["trip_id"])
    op.create_index(op.f("ix_moments_stop_id"), "moments", ["stop_id"])

    op.create_table(
        "moment_media",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("moment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        *generated_columns(),
        *generated_constraints("moment_media"),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["moment_id"], ["moments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_item_id"], ["media_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("moment_id", "media_item_id"),
    )
    op.create_index(op.f("ix_moment_media_media_item_id"), "moment_media", ["media_item_id"])

    op.create_table(
        "moment_participants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("moment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trip_member_id", postgresql.UUID(as_uuid=True), nullable=False),
        *generated_columns(),
        *generated_constraints("moment_participants"),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["moment_id"], ["moments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trip_member_id"], ["trip_members.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("moment_id", "trip_member_id"),
    )
    op.create_index(
        op.f("ix_moment_participants_trip_member_id"), "moment_participants", ["trip_member_id"]
    )

    op.create_table(
        "trip_legs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trip_day_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_stop_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_stop_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_source", sa.String(length=40), nullable=False),
        sa.Column("geometry", sa.Text()),
        *generated_columns(),
        *generated_constraints("trip_legs"),
        sa.CheckConstraint(
            "route_source IN ('photo_inferred', 'manual', 'directions_api', 'gps_track')",
            name=op.f("ck_trip_legs_route_source"),
        ),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trip_day_id"], ["trip_days.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_stop_id"], ["stops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_stop_id"], ["stops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("from_stop_id", "to_stop_id", "reconstruction_run_id"),
    )
    op.execute(
        "ALTER TABLE trip_legs ALTER COLUMN geometry TYPE geography(LineString,4326) "
        "USING geometry::geography"
    )
    op.create_index(op.f("ix_trip_legs_trip_day_id"), "trip_legs", ["trip_day_id"])
    op.create_index(
        "ix_trip_legs_geometry_gist", "trip_legs", ["geometry"], postgresql_using="gist"
    )

    op.create_table(
        "review_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_item_id", postgresql.UUID(as_uuid=True)),
        sa.Column("item_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), server_default=sa.text("'open'"), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        *generated_columns(),
        *generated_constraints("review_items"),
        sa.CheckConstraint(
            "item_type IN ('unusable_time', 'missing_gps_ambiguous', 'low_confidence_stop')",
            name=op.f("ck_review_items_item_type"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'resolved', 'dismissed')", name=op.f("ck_review_items_status")
        ),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_item_id"], ["media_items.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_review_items_trip_id"), "review_items", ["trip_id"])
    op.create_index(op.f("ix_review_items_media_item_id"), "review_items", ["media_item_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_review_items_media_item_id"), table_name="review_items")
    op.drop_index(op.f("ix_review_items_trip_id"), table_name="review_items")
    op.drop_table("review_items")
    op.drop_index("ix_trip_legs_geometry_gist", table_name="trip_legs")
    op.drop_index(op.f("ix_trip_legs_trip_day_id"), table_name="trip_legs")
    op.drop_table("trip_legs")
    op.drop_index(op.f("ix_moment_participants_trip_member_id"), table_name="moment_participants")
    op.drop_table("moment_participants")
    op.drop_index(op.f("ix_moment_media_media_item_id"), table_name="moment_media")
    op.drop_table("moment_media")
    op.drop_index(op.f("ix_moments_stop_id"), table_name="moments")
    op.drop_index(op.f("ix_moments_trip_id"), table_name="moments")
    op.drop_table("moments")
    op.drop_index("ix_stops_centroid_gist", table_name="stops")
    op.drop_index(op.f("ix_stops_trip_day_id"), table_name="stops")
    op.drop_index(op.f("ix_stops_trip_id"), table_name="stops")
    op.drop_table("stops")
    op.drop_index("ix_places_centroid_gist", table_name="places")
    op.drop_index(op.f("ix_places_trip_id"), table_name="places")
    op.drop_table("places")
    op.drop_index(op.f("ix_trip_days_trip_id"), table_name="trip_days")
    op.drop_table("trip_days")
    op.drop_index(op.f("ix_reconstruction_runs_trip_id"), table_name="reconstruction_runs")
    op.drop_table("reconstruction_runs")
