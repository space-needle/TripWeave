"""Add AreaVisit create operation.

Revision ID: 0019_area_visit_create
Revises: 0018_area_visit_delete
Create Date: 2026-08-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019_area_visit_create"
down_revision: str | None = "0018_area_visit_delete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


EDIT_TYPES = (
    "'move_media', 'move_after_midnight_media', 'merge_stops', 'split_stop', "
    "'merge_moments', 'rename_day', 'rename_stop', 'rename_moment', "
    "'create_area_visit', 'rename_area_visit', 'add_area_visit_stop', "
    "'remove_area_visit_stop', 'delete_area_visit', "
    "'set_day_note', 'set_stop_note', 'move_stop_on_map', 'change_route_mode', "
    "'exclude_media_from_story', 'lock_record', 'resolve_review_item', "
    "'dismiss_review_item', 'set_similarity_representative', "
    "'accept_clock_offset_suggestion', 'reject_clock_offset_suggestion'"
)
PREVIOUS_EDIT_TYPES = (
    "'move_media', 'move_after_midnight_media', 'merge_stops', 'split_stop', "
    "'merge_moments', 'rename_day', 'rename_stop', 'rename_moment', "
    "'rename_area_visit', 'add_area_visit_stop', 'remove_area_visit_stop', "
    "'delete_area_visit', "
    "'set_day_note', 'set_stop_note', 'move_stop_on_map', 'change_route_mode', "
    "'exclude_media_from_story', 'lock_record', 'resolve_review_item', "
    "'dismiss_review_item', 'set_similarity_representative', "
    "'accept_clock_offset_suggestion', 'reject_clock_offset_suggestion'"
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE edit_operations DROP CONSTRAINT IF EXISTS ck_edit_operations_operation_type"
    )
    op.create_check_constraint(
        op.f("ck_edit_operations_operation_type"),
        "edit_operations",
        f"operation_type IN ({EDIT_TYPES})",
    )


def downgrade() -> None:
    op.execute("DELETE FROM edit_operations WHERE operation_type = 'create_area_visit'")
    op.execute(
        "ALTER TABLE edit_operations DROP CONSTRAINT IF EXISTS ck_edit_operations_operation_type"
    )
    op.create_check_constraint(
        op.f("ck_edit_operations_operation_type"),
        "edit_operations",
        f"operation_type IN ({PREVIOUS_EDIT_TYPES})",
    )
