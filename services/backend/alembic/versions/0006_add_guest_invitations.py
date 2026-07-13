"""Add guest invitation acceptance and sessions.

Revision ID: 0006_guest_invitations
Revises: 0005_media_metadata_json
Create Date: 2026-07-13
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006_guest_invitations"
down_revision = "0005_media_metadata_json"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("trip_invitations", "email", existing_type=sa.String(length=320), nullable=True)
    op.add_column(
        "trip_invitations",
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "trip_invitations",
        sa.Column("use_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("trip_invitations", sa.Column("revoked_at", sa.DateTime(timezone=True)))
    op.add_column(
        "trip_invitations",
        sa.Column("accepted_member_id", postgresql.UUID(as_uuid=True)),
    )
    op.create_foreign_key(
        op.f("fk_trip_invitations_accepted_member_id_trip_members"),
        "trip_invitations",
        "trip_members",
        ["accepted_member_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f("ck_trip_invitations_use_count"),
        "trip_invitations",
        "use_count >= 0 AND max_uses > 0 AND use_count <= max_uses",
    )

    op.create_table(
        "guest_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["member_id", "trip_id"],
            ["trip_members.id", "trip_members.trip_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_guest_sessions_member_id", "guest_sessions", ["member_id"])
    op.create_index("ix_guest_sessions_trip_id", "guest_sessions", ["trip_id"])


def downgrade() -> None:
    op.drop_index("ix_guest_sessions_trip_id", table_name="guest_sessions")
    op.drop_index("ix_guest_sessions_member_id", table_name="guest_sessions")
    op.drop_table("guest_sessions")
    op.drop_constraint(op.f("ck_trip_invitations_use_count"), "trip_invitations", type_="check")
    op.drop_constraint(
        op.f("fk_trip_invitations_accepted_member_id_trip_members"),
        "trip_invitations",
        type_="foreignkey",
    )
    op.drop_column("trip_invitations", "accepted_member_id")
    op.drop_column("trip_invitations", "revoked_at")
    op.drop_column("trip_invitations", "use_count")
    op.drop_column("trip_invitations", "max_uses")
    op.execute("UPDATE trip_invitations SET email = '' WHERE email IS NULL")
    op.alter_column(
        "trip_invitations", "email", existing_type=sa.String(length=320), nullable=False
    )
