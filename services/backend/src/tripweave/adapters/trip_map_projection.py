from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, literal_column, select
from sqlalchemy.orm import Session

from tripweave.adapters import orm


def rebuild_trip_map_point_projection(db: Session, trip_id: UUID) -> None:
    db.execute(
        delete(orm.TripMapPointProjection).where(orm.TripMapPointProjection.trip_id == trip_id)
    )

    latitude: Any = literal_column("ST_Y(media_items.effective_location::geometry)").label(
        "latitude"
    )
    longitude: Any = literal_column("ST_X(media_items.effective_location::geometry)").label(
        "longitude"
    )
    captured_at = func.coalesce(
        orm.MediaItem.effective_captured_at_utc,
        orm.MediaItem.original_captured_at_utc,
    ).label("captured_at")
    rows = db.execute(
        select(
            orm.MediaItem.id,
            orm.MediaItem.trip_id,
            captured_at,
            latitude,
            longitude,
            orm.MediaItem.location_source,
            orm.MediaItem.location_confidence,
            orm.MediaItem.original_filename,
        )
        .where(
            orm.MediaItem.trip_id == trip_id,
            orm.MediaItem.deleted_at.is_(None),
            orm.MediaItem.effective_location.is_not(None),
        )
        .order_by(
            orm.MediaItem.effective_captured_at_utc.asc().nulls_last(),
            orm.MediaItem.created_at,
            orm.MediaItem.id,
        )
    ).all()

    for (
        media_item_id,
        media_trip_id,
        media_captured_at,
        latitude_value,
        longitude_value,
        location_source,
        location_confidence,
        original_filename,
    ) in rows:
        db.add(
            orm.TripMapPointProjection(
                trip_id=media_trip_id,
                media_item_id=media_item_id,
                captured_at=media_captured_at,
                captured_date=media_captured_at.date() if media_captured_at is not None else None,
                latitude=float(latitude_value),
                longitude=float(longitude_value),
                source=location_source,
                confidence=location_confidence,
                filename=original_filename,
            )
        )
