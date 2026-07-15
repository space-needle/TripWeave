"""Add collaboration intelligence tables.

Revision ID: 0009_collaboration_intelligence
Revises: 0008_review_edit_operations
Create Date: 2026-07-14
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0009_collaboration_intelligence"
down_revision = "0008_review_edit_operations"
branch_labels = None
depends_on = None


EDIT_TYPES = (
    "'move_media', 'move_after_midnight_media', 'merge_stops', 'split_stop', "
    "'merge_moments', 'rename_day', 'rename_stop', 'rename_moment', "
    "'move_stop_on_map', 'change_route_mode', 'exclude_media_from_story', "
    "'lock_record', 'resolve_review_item', 'dismiss_review_item', "
    "'set_similarity_representative', 'accept_clock_offset_suggestion', "
    "'reject_clock_offset_suggestion'"
)
JOB_TYPES = (
    "'ingest_media', 'metadata_extraction', 'alignment', 'grouping', "
    "'derivative_generation', 'publication', 'deletion', 'repair', "
    "'reconstruct_trip'"
)
PREVIOUS_JOB_TYPES = (
    "'ingest_media', 'metadata_extraction', 'alignment', 'grouping', "
    "'derivative_generation', 'publication', 'deletion', 'repair'"
)


def upgrade() -> None:
    op.execute("ALTER TABLE processing_jobs DROP CONSTRAINT IF EXISTS ck_processing_jobs_job_type")
    op.create_check_constraint(
        op.f("ck_processing_jobs_job_type"),
        "processing_jobs",
        f"job_type IN ({JOB_TYPES})",
    )

    op.execute(
        "ALTER TABLE edit_operations DROP CONSTRAINT IF EXISTS ck_edit_operations_operation_type"
    )
    op.create_check_constraint(
        op.f("ck_edit_operations_operation_type"),
        "edit_operations",
        f"operation_type IN ({EDIT_TYPES})",
    )

    op.create_table(
        "capture_devices",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contributor_member_id", postgresql.UUID(as_uuid=True)),
        sa.Column("device_key", sa.String(length=160), nullable=False),
        sa.Column("make", sa.String(length=160)),
        sa.Column("model", sa.String(length=160)),
        sa.Column("software", sa.String(length=160)),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("accepted_clock_offset_seconds", sa.Integer()),
        sa.Column("accepted_suggestion_id", postgresql.UUID(as_uuid=True)),
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
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["contributor_member_id"], ["trip_members.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trip_id", "device_key"),
    )
    op.create_index(op.f("ix_capture_devices_trip_id"), "capture_devices", ["trip_id"])
    op.create_index(
        op.f("ix_capture_devices_member_id"), "capture_devices", ["contributor_member_id"]
    )

    op.add_column(
        "media_items",
        sa.Column("capture_device_id", postgresql.UUID(as_uuid=True)),
    )
    op.create_foreign_key(
        op.f("fk_media_items_capture_device_id_capture_devices"),
        "media_items",
        "capture_devices",
        ["capture_device_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_media_items_capture_device_id"), "media_items", ["capture_device_id"])
    op.create_index(op.f("ix_media_items_perceptual_hash"), "media_items", ["perceptual_hash"])

    op.create_table(
        "similarity_groups",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_type", sa.String(length=40), nullable=False),
        sa.Column("representative_media_item_id", postgresql.UUID(as_uuid=True)),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
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
        sa.CheckConstraint(
            "source IN ('automation', 'user_correction', 'manual')",
            name=op.f("ck_similarity_groups_source"),
        ),
        sa.CheckConstraint(
            "group_type IN ('exact_duplicate', 'visually_similar')",
            name=op.f("ck_similarity_groups_group_type"),
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_similarity_groups_confidence"),
        ),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["representative_media_item_id"], ["media_items.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["reconstruction_run_id"], ["reconstruction_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_similarity_groups_trip_id"), "similarity_groups", ["trip_id"])
    op.create_index(
        op.f("ix_similarity_groups_representative"),
        "similarity_groups",
        ["representative_media_item_id"],
    )

    op.create_table(
        "similarity_group_members",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("similarity_group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("similarity_score", sa.Float()),
        sa.Column("technical_score", sa.Float()),
        sa.Column(
            "is_representative", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("user_selected", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "signals", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.CheckConstraint(
            "similarity_score IS NULL OR (similarity_score >= 0 AND similarity_score <= 1)",
            name=op.f("ck_similarity_group_members_similarity_score"),
        ),
        sa.CheckConstraint(
            "technical_score IS NULL OR (technical_score >= 0 AND technical_score <= 1)",
            name=op.f("ck_similarity_group_members_technical_score"),
        ),
        sa.ForeignKeyConstraint(
            ["similarity_group_id"], ["similarity_groups.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["media_item_id"], ["media_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("similarity_group_id", "media_item_id"),
    )
    op.create_index(
        op.f("ix_similarity_group_members_media"),
        "similarity_group_members",
        ["media_item_id"],
    )

    op.create_table(
        "device_clock_offset_suggestions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capture_device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("offset_seconds", sa.Integer(), nullable=False),
        sa.Column("support_count", sa.Integer(), nullable=False),
        sa.Column("dispersion_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), server_default=sa.text("'open'"), nullable=False),
        sa.Column(
            "evidence", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("rejected_at", sa.DateTime(timezone=True)),
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
        sa.CheckConstraint(
            "source IN ('automation', 'user_correction', 'manual')",
            name=op.f("ck_device_clock_offset_suggestions_source"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'accepted', 'rejected')",
            name=op.f("ck_device_clock_offset_suggestions_status"),
        ),
        sa.CheckConstraint(
            "support_count >= 0",
            name=op.f("ck_device_clock_offset_suggestions_support_count"),
        ),
        sa.CheckConstraint(
            "dispersion_seconds >= 0",
            name=op.f("ck_device_clock_offset_suggestions_dispersion_seconds"),
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_device_clock_offset_suggestions_confidence"),
        ),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["capture_device_id"], ["capture_devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["reconstruction_run_id"], ["reconstruction_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_clock_offset_suggestions_trip_status"),
        "device_clock_offset_suggestions",
        ["trip_id", "status"],
    )
    op.create_index(
        op.f("ix_clock_offset_suggestions_device"),
        "device_clock_offset_suggestions",
        ["capture_device_id"],
    )


def downgrade() -> None:
    op.execute("DELETE FROM processing_jobs WHERE job_type = 'reconstruct_trip'")
    op.execute("ALTER TABLE processing_jobs DROP CONSTRAINT IF EXISTS ck_processing_jobs_job_type")
    op.create_check_constraint(
        op.f("ck_processing_jobs_job_type"),
        "processing_jobs",
        f"job_type IN ({PREVIOUS_JOB_TYPES})",
    )

    op.drop_index(
        op.f("ix_clock_offset_suggestions_device"),
        table_name="device_clock_offset_suggestions",
    )
    op.drop_index(
        op.f("ix_clock_offset_suggestions_trip_status"),
        table_name="device_clock_offset_suggestions",
    )
    op.drop_table("device_clock_offset_suggestions")
    op.drop_index(op.f("ix_similarity_group_members_media"), table_name="similarity_group_members")
    op.drop_table("similarity_group_members")
    op.drop_index(op.f("ix_similarity_groups_representative"), table_name="similarity_groups")
    op.drop_index(op.f("ix_similarity_groups_trip_id"), table_name="similarity_groups")
    op.drop_table("similarity_groups")
    op.drop_index(op.f("ix_media_items_perceptual_hash"), table_name="media_items")
    op.drop_index(op.f("ix_media_items_capture_device_id"), table_name="media_items")
    op.drop_constraint(
        op.f("fk_media_items_capture_device_id_capture_devices"),
        "media_items",
        type_="foreignkey",
    )
    op.drop_column("media_items", "capture_device_id")
    op.drop_index(op.f("ix_capture_devices_member_id"), table_name="capture_devices")
    op.drop_index(op.f("ix_capture_devices_trip_id"), table_name="capture_devices")
    op.drop_table("capture_devices")

    op.execute(
        """
        DELETE FROM edit_operations
        WHERE operation_type IN (
            'set_similarity_representative',
            'accept_clock_offset_suggestion',
            'reject_clock_offset_suggestion'
        )
        """
    )
    op.execute(
        "ALTER TABLE edit_operations DROP CONSTRAINT IF EXISTS ck_edit_operations_operation_type"
    )
    op.create_check_constraint(
        op.f("ck_edit_operations_operation_type"),
        "edit_operations",
        (
            "operation_type IN ('move_media', 'move_after_midnight_media', "
            "'merge_stops', 'split_stop', 'merge_moments', 'rename_day', "
            "'rename_stop', 'rename_moment', 'move_stop_on_map', "
            "'change_route_mode', 'exclude_media_from_story', 'lock_record', "
            "'resolve_review_item', 'dismiss_review_item')"
        ),
    )
