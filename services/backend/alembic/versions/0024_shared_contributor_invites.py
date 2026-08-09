"""Make newly created contributor invitations shared by default.

Revision ID: 0024_shared_contributor_invites
Revises: 0023_trip_view_events
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0024_shared_contributor_invites"
down_revision: str | None = "0023_trip_view_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "trip_invitations",
        "max_uses",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default=sa.text("25"),
    )


def downgrade() -> None:
    op.alter_column(
        "trip_invitations",
        "max_uses",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default=sa.text("1"),
    )
