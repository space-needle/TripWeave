"""Record public trip story views."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0023_trip_view_events"
down_revision: str | None = "0022_subscription_tiers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trip_view_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("share_link_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "viewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["share_link_id"], ["share_links.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trip_view_events_viewed_at", "trip_view_events", ["viewed_at"])
    op.create_index(
        "ix_trip_view_events_trip_viewed_at",
        "trip_view_events",
        ["trip_id", "viewed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_trip_view_events_trip_viewed_at", table_name="trip_view_events")
    op.drop_index("ix_trip_view_events_viewed_at", table_name="trip_view_events")
    op.drop_table("trip_view_events")
