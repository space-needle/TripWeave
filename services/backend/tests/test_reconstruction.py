from datetime import UTC, datetime
from uuid import uuid4

from tripweave.adapters import orm
from tripweave.adapters.reconstruction import (
    MediaPoint,
    cluster_stops,
    effective_day,
    media_capture_utc,
)


def media_point(
    captured_at: datetime,
    *,
    latitude: float = 37.0,
    longitude: float = -122.0,
) -> MediaPoint:
    return MediaPoint(
        id=uuid4(),
        contributor_member_id=uuid4(),
        captured_at_utc=captured_at,
        original_local=None,
        utc_offset_minutes=-420,
        latitude=latitude,
        longitude=longitude,
        location_confidence=1.0,
    )


def test_midnight_cutoff_uses_local_offset() -> None:
    trip = orm.Trip(title="Trip", timezone_id="America/Los_Angeles", day_cutoff_hour=4)
    before_cutoff = media_point(datetime(2026, 7, 2, 10, 30, tzinfo=UTC))
    after_cutoff = media_point(datetime(2026, 7, 2, 11, 30, tzinfo=UTC))

    assert effective_day(trip, before_cutoff).isoformat() == "2026-07-01"
    assert effective_day(trip, after_cutoff).isoformat() == "2026-07-02"


def test_local_capture_time_uses_trip_timezone_when_offset_is_missing() -> None:
    trip = orm.Trip(title="Trip", timezone_id="America/Los_Angeles", day_cutoff_hour=4)
    media = orm.MediaItem(
        trip_id=uuid4(),
        contributor_member_id=uuid4(),
        media_type="photo",
        original_store_alias="media_private",
        original_object_key="key",
        original_captured_at_local=datetime(2026, 7, 2, 10, 30),
        sha256="a" * 64,
    )

    captured_at = media_capture_utc(trip, media)

    assert captured_at is not None
    assert captured_at.isoformat() == "2026-07-02T17:30:00+00:00"


def test_same_place_revisited_after_substantial_interval_is_new_stop() -> None:
    day = datetime(2026, 7, 2, 16, 0, tzinfo=UTC)
    points = [
        media_point(day),
        media_point(day.replace(minute=10)),
        media_point(day.replace(hour=18, minute=30)),
    ]
    for point in points:
        point.day = effective_day(
            orm.Trip(title="Trip", timezone_id="America/Los_Angeles", day_cutoff_hour=4),
            point,
        )

    clusters_by_day = cluster_stops(points)

    assert [len(clusters) for clusters in clusters_by_day.values()] == [2]


def test_parallel_contributor_path_is_not_forced_into_same_stop() -> None:
    day = datetime(2026, 7, 2, 16, 0, tzinfo=UTC)
    points = [
        media_point(day, latitude=37.0, longitude=-122.0),
        media_point(day.replace(minute=5), latitude=37.01, longitude=-122.01),
    ]
    for point in points:
        point.day = effective_day(
            orm.Trip(title="Trip", timezone_id="America/Los_Angeles", day_cutoff_hour=4),
            point,
        )

    clusters_by_day = cluster_stops(points)

    assert [len(clusters) for clusters in clusters_by_day.values()] == [2]
