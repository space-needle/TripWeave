"""Add story publication tables.

Revision ID: 0010_story_publication
Revises: 0009_collaboration_intelligence
Create Date: 2026-07-14
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0010_story_publication"
down_revision = "0009_collaboration_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "story_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "state", sa.String(length=40), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("manifest_store_alias", sa.String(length=100)),
        sa.Column("manifest_object_key", sa.Text()),
        sa.Column("manifest_checksum", sa.Text()),
        sa.Column("manifest_byte_size", sa.BigInteger()),
        sa.Column("asset_prefix", sa.Text(), nullable=False),
        sa.Column("source_reconstruction_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_by_member_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("publication_started_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(length=120)),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "audit", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
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
            "state IN ('pending', 'publishing', 'published', 'failed')",
            name=op.f("ck_story_versions_state"),
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name=op.f("ck_story_versions_version_number_positive"),
        ),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_reconstruction_run_id"], ["reconstruction_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["created_by_member_id"], ["trip_members.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trip_id", "version_number"),
    )
    op.create_index(
        op.f("ix_story_versions_trip_version"),
        "story_versions",
        ["trip_id", "version_number"],
    )
    op.create_index(op.f("ix_story_versions_trip_state"), "story_versions", ["trip_id", "state"])

    op.create_table(
        "share_links",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("story_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=40), server_default=sa.text("'active'"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True)),
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
            "status IN ('active', 'revoked', 'expired')",
            name=op.f("ck_share_links_status"),
        ),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["story_version_id"], ["story_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_share_links_trip_id"), "share_links", ["trip_id"])
    op.create_index(op.f("ix_share_links_story_version_id"), "share_links", ["story_version_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_share_links_story_version_id"), table_name="share_links")
    op.drop_index(op.f("ix_share_links_trip_id"), table_name="share_links")
    op.drop_table("share_links")
    op.drop_index(op.f("ix_story_versions_trip_state"), table_name="story_versions")
    op.drop_index(op.f("ix_story_versions_trip_version"), table_name="story_versions")
    op.drop_table("story_versions")
