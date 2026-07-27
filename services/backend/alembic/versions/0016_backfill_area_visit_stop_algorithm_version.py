"""Backfill AreaVisitStop algorithm version column.

Revision ID: 0016_area_visit_stop_algver
Revises: 0015_area_visits
Create Date: 2026-07-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016_area_visit_stop_algver"
down_revision: str | None = "0015_area_visits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE area_visit_stops ADD COLUMN IF NOT EXISTS algorithm_version varchar(80)"
    )
    op.execute(
        "UPDATE area_visit_stops "
        "SET algorithm_version = 'area_visit_v1' "
        "WHERE algorithm_version IS NULL"
    )
    op.execute("ALTER TABLE area_visit_stops ALTER COLUMN algorithm_version SET NOT NULL")


def downgrade() -> None:
    # No-op: current 0015 creates this column on fresh databases. This corrective
    # migration only repairs local databases that applied an earlier 0015 draft.
    pass
