"""Add timeline notes.

Revision ID: 0011_timeline_notes
Revises: 0010_story_publication
Create Date: 2026-07-19
"""

import sqlalchemy as sa

from alembic import op

revision = "0011_timeline_notes"
down_revision = "0010_story_publication"
branch_labels = None
depends_on = None


EDIT_TYPES = (
    "'move_media', 'move_after_midnight_media', 'merge_stops', 'split_stop', "
    "'merge_moments', 'rename_day', 'rename_stop', 'rename_moment', "
    "'set_day_note', 'set_stop_note', "
    "'move_stop_on_map', 'change_route_mode', 'exclude_media_from_story', "
    "'lock_record', 'resolve_review_item', 'dismiss_review_item', "
    "'set_similarity_representative', 'accept_clock_offset_suggestion', "
    "'reject_clock_offset_suggestion'"
)
PREVIOUS_EDIT_TYPES = (
    "'move_media', 'move_after_midnight_media', 'merge_stops', 'split_stop', "
    "'merge_moments', 'rename_day', 'rename_stop', 'rename_moment', "
    "'move_stop_on_map', 'change_route_mode', 'exclude_media_from_story', "
    "'lock_record', 'resolve_review_item', 'dismiss_review_item', "
    "'set_similarity_representative', 'accept_clock_offset_suggestion', "
    "'reject_clock_offset_suggestion'"
)


def upgrade() -> None:
    op.add_column("trip_days", sa.Column("note", sa.Text()))
    op.add_column("stops", sa.Column("note", sa.Text()))
    op.execute(
        "ALTER TABLE edit_operations DROP CONSTRAINT IF EXISTS ck_edit_operations_operation_type"
    )
    op.create_check_constraint(
        op.f("ck_edit_operations_operation_type"),
        "edit_operations",
        f"operation_type IN ({EDIT_TYPES})",
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE edit_operations DROP CONSTRAINT IF EXISTS ck_edit_operations_operation_type"
    )
    op.execute(
        "DELETE FROM edit_operations WHERE operation_type IN ('set_day_note', 'set_stop_note')"
    )
    op.create_check_constraint(
        op.f("ck_edit_operations_operation_type"),
        "edit_operations",
        f"operation_type IN ({PREVIOUS_EDIT_TYPES})",
    )
    op.drop_column("stops", "note")
    op.drop_column("trip_days", "note")
