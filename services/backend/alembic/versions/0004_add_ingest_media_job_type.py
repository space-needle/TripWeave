"""Add ingest media processing job type.

Revision ID: 0004_ingest_media_job
Revises: 0003_editor_member_role
Create Date: 2026-07-13
"""

from alembic import op

revision = "0004_ingest_media_job"
down_revision = "0003_editor_member_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE processing_jobs
        DROP CONSTRAINT ck_processing_jobs_job_type
        """
    )
    op.execute(
        """
        ALTER TABLE processing_jobs
        ADD CONSTRAINT ck_processing_jobs_job_type CHECK (
            job_type IN (
                'ingest_media',
                'metadata_extraction',
                'alignment',
                'grouping',
                'derivative_generation',
                'publication',
                'deletion',
                'repair'
            )
        )
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM processing_jobs WHERE job_type = 'ingest_media'")
    op.execute(
        """
        ALTER TABLE processing_jobs
        DROP CONSTRAINT ck_processing_jobs_job_type
        """
    )
    op.execute(
        """
        ALTER TABLE processing_jobs
        ADD CONSTRAINT ck_processing_jobs_job_type CHECK (
            job_type IN (
                'metadata_extraction',
                'alignment',
                'grouping',
                'derivative_generation',
                'publication',
                'deletion',
                'repair'
            )
        )
        """
    )
