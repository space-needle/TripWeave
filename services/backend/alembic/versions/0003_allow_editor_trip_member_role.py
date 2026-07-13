"""Allow editor trip member role.

Revision ID: 0003_editor_member_role
Revises: 0002_create_domain_foundation
Create Date: 2026-07-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_editor_member_role"
down_revision: str | None = "0002_create_domain_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_CHECK = "role IN ('owner', 'editor', 'contributor', 'viewer')"
OLD_ROLE_CHECK = "role IN ('owner', 'contributor', 'viewer')"


def upgrade() -> None:
    op.execute("ALTER TABLE trip_members DROP CONSTRAINT ck_trip_members_role")
    op.execute(f"ALTER TABLE trip_members ADD CONSTRAINT ck_trip_members_role CHECK ({ROLE_CHECK})")
    op.execute("ALTER TABLE trip_invitations DROP CONSTRAINT ck_trip_invitations_role")
    op.execute(
        f"ALTER TABLE trip_invitations ADD CONSTRAINT ck_trip_invitations_role CHECK ({ROLE_CHECK})"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE trip_invitations DROP CONSTRAINT ck_trip_invitations_role")
    op.execute(
        "ALTER TABLE trip_invitations "
        f"ADD CONSTRAINT ck_trip_invitations_role CHECK ({OLD_ROLE_CHECK})"
    )
    op.execute("ALTER TABLE trip_members DROP CONSTRAINT ck_trip_members_role")
    op.execute(
        f"ALTER TABLE trip_members ADD CONSTRAINT ck_trip_members_role CHECK ({OLD_ROLE_CHECK})"
    )
