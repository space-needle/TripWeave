import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

from tripweave.adapters import orm
from tripweave.adapters.manual_geocoder import ManualGeocoder, ManualPlaceName
from tripweave.adapters.nominatim_geocoder import NominatimGeocoder, geocode_result_from_nominatim
from tripweave.adapters.reconstruction import (
    MediaPoint,
    cluster_stops,
    contributor_trace_edges_for_points,
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


def test_contributor_trace_edges_preserve_fork_and_join_paths() -> None:
    contributor_a = uuid4()
    contributor_b = uuid4()
    stop_one = orm.Stop(id=uuid4(), position=1)
    stop_two_a = orm.Stop(id=uuid4(), position=2)
    stop_two_b = orm.Stop(id=uuid4(), position=3)
    stop_three = orm.Stop(id=uuid4(), position=4)
    day = datetime(2026, 7, 2, 16, 0, tzinfo=UTC)
    points = [
        media_point(day, latitude=37.0, longitude=-122.0),
        media_point(day.replace(minute=5), latitude=37.0, longitude=-122.0),
        media_point(day.replace(hour=17), latitude=37.01, longitude=-122.01),
        media_point(day.replace(hour=17, minute=2), latitude=37.02, longitude=-122.02),
        media_point(day.replace(hour=18), latitude=37.03, longitude=-122.03),
        media_point(day.replace(hour=18, minute=5), latitude=37.03, longitude=-122.03),
    ]
    for point, contributor_id, stop in [
        (points[0], contributor_a, stop_one),
        (points[1], contributor_b, stop_one),
        (points[2], contributor_a, stop_two_a),
        (points[3], contributor_b, stop_two_b),
        (points[4], contributor_a, stop_three),
        (points[5], contributor_b, stop_three),
    ]:
        point.contributor_member_id = contributor_id
        point.stop = stop

    edges = contributor_trace_edges_for_points(points)

    assert edges == [
        (stop_one.id, stop_two_a.id),
        (stop_two_a.id, stop_three.id),
        (stop_one.id, stop_two_b.id),
        (stop_two_b.id, stop_three.id),
    ]


def test_manual_reverse_geocoder_returns_registered_place_name() -> None:
    geocoder = ManualGeocoder(
        [
            ManualPlaceName(
                name="Jeonju Hanok Village",
                latitude=35.8151,
                longitude=127.1530,
                radius_meters=100,
                confidence=0.82,
            )
        ]
    )

    result = geocoder.reverse_geocode(latitude=35.8152, longitude=127.1531)

    assert result.name == "Jeonju Hanok Village"
    assert result.confidence == 0.82
    assert result.source == "manual"


def test_manual_reverse_geocoder_is_noop_without_nearby_place() -> None:
    geocoder = ManualGeocoder(
        [ManualPlaceName(name="Jeonju Hanok Village", latitude=35.8151, longitude=127.1530)]
    )

    result = geocoder.reverse_geocode(latitude=37.5665, longitude=126.9780)

    assert result.name is None
    assert result.confidence is None


def test_nominatim_result_prefers_poi_name_over_address() -> None:
    result = geocode_result_from_nominatim(
        {
            "category": "amenity",
            "type": "restaurant",
            "name": "Veteran Kalguksu",
            "importance": 0.64,
            "address": {
                "road": "Taejo-ro",
                "neighbourhood": "Jeonju Hanok Village",
                "city": "Jeonju",
            },
        }
    )

    assert result.name == "Veteran Kalguksu"
    assert result.confidence == 0.64
    assert result.source == "nominatim"


def test_nominatim_result_falls_back_to_neighbourhood_not_full_address() -> None:
    result = geocode_result_from_nominatim(
        {
            "category": "highway",
            "type": "residential",
            "display_name": "44, Taejo-ro, Wansan-gu, Jeonju, Jeollabuk-do, South Korea",
            "address": {
                "road": "Taejo-ro",
                "neighbourhood": "Jeonju Hanok Village",
                "city": "Jeonju",
            },
        }
    )

    assert result.name == "Jeonju Hanok Village"


def test_nominatim_geocoder_serializes_requests_in_one_process() -> None:
    active_requests = 0
    max_active_requests = 0
    lock = threading.Lock()

    def opener(_request: object, _timeout_seconds: float) -> bytes:
        nonlocal active_requests, max_active_requests
        with lock:
            active_requests += 1
            max_active_requests = max(max_active_requests, active_requests)
        time.sleep(0.01)
        with lock:
            active_requests -= 1
        return b'{"category":"amenity","type":"cafe","name":"Hanok Cafe"}'

    geocoder = NominatimGeocoder(min_interval_seconds=0, opener=opener)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda index: geocoder.reverse_geocode(
                    latitude=35.815 + index * 0.001,
                    longitude=127.153,
                ),
                range(2),
            )
        )

    assert [result.name for result in results] == ["Hanok Cafe", "Hanok Cafe"]
    assert max_active_requests == 1
