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


def test_effective_capture_utc_uses_trip_timezone_for_local_only_metadata() -> None:
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
        latitude=None,
        longitude=None,
        camera_hints={},
        derivatives=(),
        raw_metadata={},
        perceptual_hash="0" * 16,
        quality_signals={},
    )

    captured_at = effective_capture_utc(FakeSession(trip), media_item, processed)  # type: ignore[arg-type]

    assert captured_at is not None
    assert captured_at.isoformat() == "2023-06-05T01:14:57+00:00"
