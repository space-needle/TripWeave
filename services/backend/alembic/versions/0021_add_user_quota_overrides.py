"""Add per-user pilot quota overrides.

Revision ID: 0021_user_quota_overrides
Revises: 0020_trip_map_point_projections
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0021_user_quota_overrides"
down_revision: str | None = "0020_trip_map_point_projections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_quota_overrides",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("max_trips_per_user", sa.Integer()),
        sa.Column("max_files_per_trip", sa.Integer()),
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
            "max_trips_per_user IS NOT NULL OR max_files_per_trip IS NOT NULL",
            name="at_least_one_limit",
        ),
        sa.CheckConstraint(
            "max_trips_per_user IS NULL OR max_trips_per_user > 0", name="max_trips_per_user"
        ),
        sa.CheckConstraint(
            "max_files_per_trip IS NULL OR max_files_per_trip > 0", name="max_files_per_trip"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_quota_overrides")
