"""Add original retention state to media items.

Revision ID: 0012_original_retention
Revises: 0011_timeline_notes
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "0012_original_retention"
down_revision = "0011_timeline_notes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "media_items",
        sa.Column(
            "original_retention_state",
            sa.String(length=40),
            nullable=False,
            server_default="retained",
        ),
    )
    op.add_column(
        "media_items",
        sa.Column("original_deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_media_items_original_retention_state"),
        "media_items",
        "original_retention_state IN ('temporary', 'retained', 'deleted')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_media_items_original_retention_state"),
        "media_items",
        type_="check",
    )
    op.drop_column("media_items", "original_deleted_at")
    op.drop_column("media_items", "original_retention_state")
