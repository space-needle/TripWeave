"""Add the local boundary used for Korean place-name selection.

Revision ID: 0030_korea_country_boundary
Revises: 0029_saved_stories
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0030_korea_country_boundary"
down_revision: str | None = "0029_saved_stories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Natural Earth 1:110m Admin 0 Countries, with island coverage for Jeju and
# Ulleungdo/Dokdo so Korean island trips receive Korean place names.
KOREA_BOUNDARY_WKT = """MULTIPOLYGON(
((126.174759 37.749686,126.237339 37.840378,126.683720 37.804773,
127.073309 38.256115,127.780035 38.304536,128.205746 38.370397,
128.349716 38.612243,129.212920 37.432392,129.460450 36.784189,
129.468304 35.632141,129.091377 35.082484,128.185850 34.890377,
127.386519 34.475674,126.485748 34.390046,126.373920 34.934560,
126.559231 35.684541,126.117398 36.725485,126.860143 36.893924,
126.174759 37.749686)),
((126.100000 33.100000,126.100000 33.700000,126.980000 33.700000,
126.980000 33.100000,126.100000 33.100000)),
((130.700000 37.350000,130.700000 37.600000,131.950000 37.600000,
131.950000 37.350000,130.700000 37.350000))
)"""


def upgrade() -> None:
    op.create_table(
        "country_boundaries",
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("boundary", sa.Text(), nullable=False),
        sa.Column("dataset", sa.String(length=120), nullable=False),
        sa.PrimaryKeyConstraint("country_code"),
    )
    op.execute(
        "ALTER TABLE country_boundaries ALTER COLUMN boundary "
        "TYPE geography(MultiPolygon,4326) USING boundary::geography"
    )
    op.execute(
        sa.text(
            """
            INSERT INTO country_boundaries (country_code, boundary, dataset)
            VALUES ('KR', ST_GeogFromText(:boundary), 'Natural Earth 1:110m + island coverage')
            """
        ).bindparams(boundary=KOREA_BOUNDARY_WKT)
    )
    op.create_index(
        "ix_country_boundaries_boundary_gist",
        "country_boundaries",
        ["boundary"],
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.drop_index("ix_country_boundaries_boundary_gist", table_name="country_boundaries")
    op.drop_table("country_boundaries")
