"""Add stable public story slugs.

Revision ID: 0027_public_story_slugs
Revises: 0026_move_media_on_map
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0027_public_story_slugs"
down_revision: str | None = "0026_move_media_on_map"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trips", sa.Column("public_story_slug", sa.String(length=220), nullable=True))
    op.create_unique_constraint("uq_trips_public_story_slug", "trips", ["public_story_slug"])
    op.execute(
        """
        UPDATE trips
        SET public_story_slug = left(
            coalesce(
                nullif(
                    trim(both '-' from regexp_replace(lower(title), '[^a-z0-9]+', '-', 'g')),
                    ''
                ),
                'trip'
            ),
            200
        ) || '-' || substring(replace(id::text, '-', '') from 1 for 12)
        WHERE EXISTS (SELECT 1 FROM share_links WHERE share_links.trip_id = trips.id)
        """
    )


def downgrade() -> None:
    op.drop_constraint("uq_trips_public_story_slug", "trips", type_="unique")
    op.drop_column("trips", "public_story_slug")
