from dataclasses import replace
from datetime import datetime
from uuid import uuid4

from tripweave.adapters import orm
from tripweave.application.media_processing import ProcessedMedia
from tripweave.entrypoints.worker.main import effective_capture_utc


class FakeSession:
    def __init__(self, trip: orm.Trip) -> None:
        self.trip = trip

    def get(self, model: type[object], _id: object) -> object | None:
        if model is orm.Trip:
            return self.trip
        return None


def test_effective_capture_utc_uses_gps_timezone_for_local_only_metadata() -> None:
    trip_id = uuid4()
    trip = orm.Trip(id=trip_id, title="Korea", timezone_id="Asia/Seoul", created_by=uuid4())
    media_item = orm.MediaItem(
        id=uuid4(),
        trip_id=trip_id,
        contributor_member_id=uuid4(),
        media_type="photo",
        original_store_alias="media_private",
        original_object_key="original.jpg",
        original_filename="original.jpg",
        sha256="a" * 64,
    )
    processed = ProcessedMedia(
        detected_mime_type="image/jpeg",
        sha256="a" * 64,
        width=100,
        height=100,
        orientation=None,
        captured_at_local=datetime(2023, 6, 5, 10, 14, 57),
        captured_at_utc=None,
        utc_offset_minutes=None,
        latitude=37.5665,
        longitude=126.978,
        camera_hints={},
        derivatives=(),
        raw_metadata={},
        perceptual_hash="0" * 16,
        quality_signals={},
    )

    captured_at = effective_capture_utc(FakeSession(trip), media_item, processed)  # type: ignore[arg-type]

    assert captured_at is not None
    assert captured_at.isoformat() == "2023-06-05T01:14:57+00:00"

    los_angeles = replace(
        processed,
        captured_at_local=datetime(2023, 6, 5, 9, 14, 57),
        latitude=34.0522,
        longitude=-118.2437,
    )
    arrived_at = effective_capture_utc(FakeSession(trip), media_item, los_angeles)  # type: ignore[arg-type]

    assert arrived_at is not None
    assert arrived_at.isoformat() == "2023-06-05T16:14:57+00:00"
    assert captured_at < arrived_at


def test_effective_capture_utc_keeps_unknown_local_time_without_gps_or_offset() -> None:
    media_item = orm.MediaItem(
        id=uuid4(),
        trip_id=uuid4(),
        contributor_member_id=uuid4(),
        media_type="photo",
        original_store_alias="media_private",
        original_object_key="original.jpg",
        original_filename="original.jpg",
        sha256="a" * 64,
    )
    processed = ProcessedMedia(
        detected_mime_type="image/jpeg",
        sha256="a" * 64,
        width=100,
        height=100,
        orientation=None,
        captured_at_local=datetime(2023, 6, 5, 10, 14, 57),
        captured_at_utc=None,
        utc_offset_minutes=None,
        latitude=None,
        longitude=None,
        camera_hints={},
        derivatives=(),
        raw_metadata={},
        perceptual_hash="0" * 16,
        quality_signals={},
    )

    trip = orm.Trip(title="Trip", timezone_id="UTC", created_by=uuid4())
    assert effective_capture_utc(FakeSession(trip), media_item, processed) is None  # type: ignore[arg-type]
