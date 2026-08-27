"""Add persistent public invitation identifiers.

Revision ID: 0028_public_invite_ids
Revises: 0027_public_story_slugs
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0028_public_invite_ids"
down_revision: str | None = "0027_public_story_slugs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "trip_invitations", sa.Column("public_invite_id", sa.String(length=36), nullable=True)
    )
    op.create_unique_constraint(
        "uq_trip_invitations_public_invite_id", "trip_invitations", ["public_invite_id"]
    )
    op.execute(
        "UPDATE trip_invitations SET public_invite_id = gen_random_uuid()::text "
        "WHERE public_invite_id IS NULL"
    )


def downgrade() -> None:
    op.drop_constraint("uq_trip_invitations_public_invite_id", "trip_invitations", type_="unique")
    op.drop_column("trip_invitations", "public_invite_id")
