"""Add cached private story draft projections.

Revision ID: 0013_story_draft_projections
Revises: 0012_original_retention
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0013_story_draft_projections"
down_revision = "0012_original_retention"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "story_draft_projections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_reconstruction_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_reconstruction_run_id"], ["reconstruction_runs.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("trip_id"),
    )
    op.create_index(
        op.f("ix_story_draft_projections_trip_run"),
        "story_draft_projections",
        ["trip_id", "source_reconstruction_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_story_draft_projections_trip_run"),
        table_name="story_draft_projections",
    )
    op.drop_table("story_draft_projections")
