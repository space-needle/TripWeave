"""Add safe original metadata JSON to media items.

Revision ID: 0005_media_metadata_json
Revises: 0004_ingest_media_job
Create Date: 2026-07-13
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005_media_metadata_json"
down_revision = "0004_ingest_media_job"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "media_items",
        sa.Column(
            "original_metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("media_items", "original_metadata_json")
