"""Add AreaVisit review and edit operation types.

Revision ID: 0017_area_visit_review_types
Revises: 0016_area_visit_stop_algver
Create Date: 2026-07-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017_area_visit_review_types"
down_revision: str | None = "0016_area_visit_stop_algver"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


REVIEW_TYPES = (
    "'unknown_time', 'unknown_location', 'possible_wrong_day', "
    "'possible_stop_merge', 'possible_stop_split', 'possible_area_visit', "
    "'possible_clock_offset', 'unassigned_media', 'failed_media_processing'"
)
PREVIOUS_REVIEW_TYPES = (
    "'unknown_time', 'unknown_location', 'possible_wrong_day', "
    "'possible_stop_merge', 'possible_stop_split', 'possible_clock_offset', "
    "'unassigned_media', 'failed_media_processing'"
)
EDIT_TYPES = (
    "'move_media', 'move_after_midnight_media', 'merge_stops', 'split_stop', "
    "'merge_moments', 'rename_day', 'rename_stop', 'rename_moment', "
    "'rename_area_visit', 'add_area_visit_stop', 'remove_area_visit_stop', "
    "'set_day_note', 'set_stop_note', 'move_stop_on_map', 'change_route_mode', "
    "'exclude_media_from_story', 'lock_record', 'resolve_review_item', "
    "'dismiss_review_item', 'set_similarity_representative', "
    "'accept_clock_offset_suggestion', 'reject_clock_offset_suggestion'"
)
PREVIOUS_EDIT_TYPES = (
    "'move_media', 'move_after_midnight_media', 'merge_stops', 'split_stop', "
    "'merge_moments', 'rename_day', 'rename_stop', 'rename_moment', "
    "'set_day_note', 'set_stop_note', 'move_stop_on_map', 'change_route_mode', "
    "'exclude_media_from_story', 'lock_record', 'resolve_review_item', "
    "'dismiss_review_item', 'set_similarity_representative', "
    "'accept_clock_offset_suggestion', 'reject_clock_offset_suggestion'"
)


def upgrade() -> None:
    op.execute("ALTER TABLE review_items DROP CONSTRAINT IF EXISTS ck_review_items_item_type")
    op.create_check_constraint(
        op.f("ck_review_items_item_type"),
        "review_items",
        f"item_type IN ({REVIEW_TYPES})",
    )
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
        "UPDATE review_items "
        "SET item_type = 'possible_stop_split' "
        "WHERE item_type = 'possible_area_visit'"
    )
    op.execute("ALTER TABLE review_items DROP CONSTRAINT IF EXISTS ck_review_items_item_type")
    op.create_check_constraint(
        op.f("ck_review_items_item_type"),
        "review_items",
        f"item_type IN ({PREVIOUS_REVIEW_TYPES})",
    )
    op.execute(
        "DELETE FROM edit_operations "
        "WHERE operation_type IN ("
        "'rename_area_visit', 'add_area_visit_stop', 'remove_area_visit_stop'"
        ")"
    )
    op.execute(
        "ALTER TABLE edit_operations DROP CONSTRAINT IF EXISTS ck_edit_operations_operation_type"
    )
    op.create_check_constraint(
        op.f("ck_edit_operations_operation_type"),
        "edit_operations",
        f"operation_type IN ({PREVIOUS_EDIT_TYPES})",
    )
