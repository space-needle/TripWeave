"""Replace quota overrides with subscription tiers."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0022_subscription_tiers"
down_revision: str | None = "0021_user_quota_overrides"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "subscription_tiers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("slug", sa.String(80), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("max_trips_per_user", sa.Integer()),
        sa.Column("max_files_per_trip", sa.Integer()),
        sa.Column("monthly_upload_bytes", sa.BigInteger(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
    )
    op.create_table(
        "user_tier_assignments",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tier_id"], ["subscription_tiers.id"], ondelete="RESTRICT"),
    )
    op.execute(
        """
        INSERT INTO subscription_tiers
            (slug, name, max_trips_per_user, max_files_per_trip, monthly_upload_bytes)
        VALUES
            ('basic', 'Basic', 5, 100, 2147483648),
            ('plus', 'Plus', 10, 200, 10737418240),
            ('unlimited', 'Unlimited', NULL, NULL, 53687091200)
        """
    )
    op.execute(
        """
        INSERT INTO user_tier_assignments (user_id, tier_id)
        SELECT users.id, subscription_tiers.id
        FROM users CROSS JOIN subscription_tiers
        WHERE subscription_tiers.slug = 'basic'
        """
    )
    op.drop_table("user_quota_overrides")


def downgrade() -> None:
    op.create_table(
        "user_quota_overrides",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("max_trips_per_user", sa.Integer()),
        sa.Column("max_files_per_trip", sa.Integer()),
    )
    op.drop_table("user_tier_assignments")
    op.drop_table("subscription_tiers")
