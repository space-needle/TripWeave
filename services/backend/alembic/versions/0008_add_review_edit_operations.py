"""Add review correction edit operations.

Revision ID: 0008_review_edit_operations
Revises: 0007_reconstruction
Create Date: 2026-07-13
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0008_review_edit_operations"
down_revision = "0007_reconstruction"
branch_labels = None
depends_on = None


REVIEW_TYPES = (
    "'unknown_time', 'unknown_location', 'possible_wrong_day', "
    "'possible_stop_merge', 'possible_stop_split', 'possible_clock_offset', "
    "'unassigned_media', 'failed_media_processing'"
)
REVIEW_SEVERITIES = "'low', 'medium', 'high', 'critical'"
EDIT_TYPES = (
    "'move_media', 'move_after_midnight_media', 'merge_stops', 'split_stop', "
    "'merge_moments', 'rename_day', 'rename_stop', 'rename_moment', "
    "'move_stop_on_map', 'change_route_mode', 'exclude_media_from_story', "
    "'lock_record', 'resolve_review_item', 'dismiss_review_item'"
)


def upgrade() -> None:
    op.add_column("trip_days", sa.Column("title", sa.String(length=255)))
    op.add_column("stops", sa.Column("title", sa.String(length=255)))
    op.add_column("moments", sa.Column("title", sa.String(length=255)))

    op.execute("ALTER TABLE review_items DROP CONSTRAINT IF EXISTS ck_review_items_item_type")
    op.execute(
        """
        UPDATE review_items
        SET item_type = CASE item_type
            WHEN 'unusable_time' THEN 'unknown_time'
            WHEN 'missing_gps_ambiguous' THEN 'unknown_location'
            WHEN 'low_confidence_stop' THEN 'possible_stop_split'
            ELSE item_type
        END
        """
    )
    op.add_column(
        "review_items",
        sa.Column(
            "severity",
            sa.String(length=40),
            server_default=sa.text("'medium'"),
            nullable=False,
        ),
    )
    op.add_column("review_items", sa.Column("target_type", sa.String(length=80)))
    op.add_column("review_items", sa.Column("target_id", postgresql.UUID(as_uuid=True)))
    op.add_column(
        "review_items",
        sa.Column(
            "target_refs",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("review_items", sa.Column("resolution", sa.Text()))
    op.add_column("review_items", sa.Column("resolved_by", postgresql.UUID(as_uuid=True)))
    op.add_column("review_items", sa.Column("resolved_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        op.f("ck_review_items_item_type"),
        "review_items",
        f"item_type IN ({REVIEW_TYPES})",
    )
    op.create_check_constraint(
        op.f("ck_review_items_severity"),
        "review_items",
        f"severity IN ({REVIEW_SEVERITIES})",
    )
    op.create_foreign_key(
        op.f("fk_review_items_resolved_by_users"),
        "review_items",
        "users",
        ["resolved_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_review_items_trip_status"), "review_items", ["trip_id", "status"])

    op.create_table(
        "edit_operations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation_type", sa.String(length=80), nullable=False),
        sa.Column(
            "status", sa.String(length=40), server_default=sa.text("'applied'"), nullable=False
        ),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("actor_member_id", postgresql.UUID(as_uuid=True)),
        sa.Column("review_item_id", postgresql.UUID(as_uuid=True)),
        sa.Column("target_type", sa.String(length=80)),
        sa.Column("target_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "before_values",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "after_values",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("undo_of_operation_id", postgresql.UUID(as_uuid=True)),
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
            f"operation_type IN ({EDIT_TYPES})", name=op.f("ck_edit_operations_operation_type")
        ),
        sa.CheckConstraint(
            "status IN ('applied', 'undone')", name=op.f("ck_edit_operations_status")
        ),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_member_id"], ["trip_members.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["review_item_id"], ["review_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["undo_of_operation_id"], ["edit_operations.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_edit_operations_trip_created"), "edit_operations", ["trip_id", "created_at"]
    )
    op.create_index(
        op.f("ix_edit_operations_review_item_id"), "edit_operations", ["review_item_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_edit_operations_review_item_id"), table_name="edit_operations")
    op.drop_index(op.f("ix_edit_operations_trip_created"), table_name="edit_operations")
    op.drop_table("edit_operations")
    op.drop_index(op.f("ix_review_items_trip_status"), table_name="review_items")
    op.drop_constraint(
        op.f("fk_review_items_resolved_by_users"), "review_items", type_="foreignkey"
    )
    op.drop_constraint(op.f("ck_review_items_severity"), "review_items", type_="check")
    op.execute("ALTER TABLE review_items DROP CONSTRAINT IF EXISTS ck_review_items_item_type")
    op.execute(
        "ALTER TABLE review_items DROP CONSTRAINT IF EXISTS "
        "ck_review_items_ck_review_items_item_type"
    )
    op.execute(
        """
        UPDATE review_items
        SET item_type = CASE item_type
            WHEN 'unknown_time' THEN 'unusable_time'
            WHEN 'unknown_location' THEN 'missing_gps_ambiguous'
            WHEN 'possible_stop_split' THEN 'low_confidence_stop'
            ELSE 'low_confidence_stop'
        END
        """
    )
    op.drop_column("review_items", "resolved_at")
    op.drop_column("review_items", "resolved_by")
    op.drop_column("review_items", "resolution")
    op.drop_column("review_items", "target_refs")
    op.drop_column("review_items", "target_id")
    op.drop_column("review_items", "target_type")
    op.drop_column("review_items", "severity")
    op.create_check_constraint(
        op.f("ck_review_items_item_type"),
        "review_items",
        "item_type IN ('unusable_time', 'missing_gps_ambiguous', 'low_confidence_stop')",
    )
    op.drop_column("moments", "title")
    op.drop_column("stops", "title")
    op.drop_column("trip_days", "title")
