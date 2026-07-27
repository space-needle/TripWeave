from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

from tripweave.adapters import orm
from tripweave.adapters.area_visit_persistence import persist_grouping_result
from tripweave.application.area_visits import (
    AreaRejectionReason,
    AreaVisitConfig,
    StopInput,
    group_area_visits,
)

BASE_TIME = datetime(2026, 6, 26, 17, 0, tzinfo=UTC)
BASE_LATITUDE = 47.6537
BASE_LONGITUDE = -122.3078
DEFAULT_COORDINATE = object()


def area_stop(
    sort_order: int,
    *,
    minutes: int | None = None,
    latitude: float | None | object = DEFAULT_COORDINATE,
    longitude: float | None | object = DEFAULT_COORDINATE,
    confidence: float | None = 1.0,
    day_id: str = "day-1",
) -> StopInput:
    start_time = BASE_TIME + timedelta(minutes=minutes if minutes is not None else sort_order * 10)
    resolved_latitude = (
        BASE_LATITUDE + sort_order * 0.0005 if latitude is DEFAULT_COORDINATE else latitude
    )
    resolved_longitude = BASE_LONGITUDE if longitude is DEFAULT_COORDINATE else longitude
    return StopInput(
        id=f"stop-{sort_order}",
        day_id=day_id,
        sort_order=sort_order,
        start_time=start_time,
        end_time=start_time + timedelta(minutes=5),
        latitude=resolved_latitude if isinstance(resolved_latitude, float) else None,
        longitude=resolved_longitude if isinstance(resolved_longitude, float) else None,
        location_confidence=confidence,
    )


def test_five_close_sequential_stops_form_one_area() -> None:
    stops = [area_stop(index) for index in range(1, 6)]

    result = group_area_visits(stops)

    assert [area.stop_ids for area in result.areas] == [
        ["stop-1", "stop-2", "stop-3", "stop-4", "stop-5"]
    ]
    assert result.standalone_stops == []
    assert result.areas[0].algorithm_version == "area_visit_v1"


def test_two_close_stops_remain_standalone() -> None:
    result = group_area_visits([area_stop(1), area_stop(2)])

    assert result.areas == []
    assert [stop.stop_id for stop in result.standalone_stops] == ["stop-1", "stop-2"]


def test_distant_next_stop_ends_current_area() -> None:
    stops = [
        area_stop(1),
        area_stop(2),
        area_stop(3),
        area_stop(4, latitude=47.70, longitude=-122.30),
    ]

    result = group_area_visits(stops)

    assert [area.stop_ids for area in result.areas] == [["stop-1", "stop-2", "stop-3"]]
    assert [stop.stop_id for stop in result.standalone_stops] == ["stop-4"]
    assert result.diagnostics[-1].rejection_reason == AreaRejectionReason.PREVIOUS_DISTANCE_EXCEEDED


def test_chaining_is_prevented_by_area_diameter_limit() -> None:
    config = AreaVisitConfig(max_area_diameter_meters=500)
    stops = [
        area_stop(1, latitude=BASE_LATITUDE),
        area_stop(2, latitude=BASE_LATITUDE + 0.002),
        area_stop(3, latitude=BASE_LATITUDE + 0.004),
        area_stop(4, latitude=BASE_LATITUDE + 0.006),
    ]

    result = group_area_visits(stops, config)

    assert [area.stop_ids for area in result.areas] == [["stop-1", "stop-2", "stop-3"]]
    assert [stop.stop_id for stop in result.standalone_stops] == ["stop-4"]
    assert result.diagnostics[-1].rejection_reason == AreaRejectionReason.AREA_DIAMETER_EXCEEDED


def test_large_time_gap_creates_separate_visit() -> None:
    stops = [
        area_stop(1, minutes=0),
        area_stop(2, minutes=10),
        area_stop(3, minutes=20),
        area_stop(4, minutes=320),
        area_stop(5, minutes=330),
        area_stop(6, minutes=340),
    ]

    result = group_area_visits(stops)

    assert [area.stop_ids for area in result.areas] == [
        ["stop-1", "stop-2", "stop-3"],
        ["stop-4", "stop-5", "stop-6"],
    ]
    assert result.standalone_stops == []


def test_returning_to_same_location_later_creates_another_area() -> None:
    stops = [
        area_stop(1, minutes=0, latitude=BASE_LATITUDE),
        area_stop(2, minutes=10, latitude=BASE_LATITUDE + 0.0005),
        area_stop(3, minutes=20, latitude=BASE_LATITUDE + 0.001),
        area_stop(4, minutes=90, latitude=47.61, longitude=-122.33),
        area_stop(5, minutes=180, latitude=BASE_LATITUDE),
        area_stop(6, minutes=190, latitude=BASE_LATITUDE + 0.0005),
        area_stop(7, minutes=200, latitude=BASE_LATITUDE + 0.001),
    ]

    result = group_area_visits(stops)

    assert [area.stop_ids for area in result.areas] == [
        ["stop-1", "stop-2", "stop-3"],
        ["stop-5", "stop-6", "stop-7"],
    ]
    assert [stop.stop_id for stop in result.standalone_stops] == ["stop-4"]


def test_missing_location_stops_do_not_crash_grouping() -> None:
    stops = [
        area_stop(1),
        area_stop(2),
        area_stop(3, latitude=None, longitude=None),
        area_stop(4),
    ]

    result = group_area_visits(stops)

    assert result.areas == []
    assert [stop.stop_id for stop in result.standalone_stops] == [
        "stop-1",
        "stop-2",
        "stop-3",
        "stop-4",
    ]
    assert any(
        diagnostic.rejection_reason == AreaRejectionReason.INVALID_OR_MISSING_LOCATION
        for diagnostic in result.diagnostics
    )


def test_low_confidence_locations_do_not_create_area_boundary_by_themselves() -> None:
    stops = [
        area_stop(1),
        area_stop(2, confidence=0.2),
        area_stop(3),
        area_stop(4),
    ]

    result = group_area_visits(stops)

    assert [area.stop_ids for area in result.areas] == [["stop-1", "stop-2", "stop-3", "stop-4"]]
    assert result.areas[0].confidence == 0.8


def test_valid_broad_area_keeps_review_friendly_confidence() -> None:
    stops = [
        area_stop(1, latitude=BASE_LATITUDE),
        area_stop(2, latitude=BASE_LATITUDE + 0.002),
        area_stop(3, latitude=BASE_LATITUDE + 0.004),
        area_stop(4, latitude=BASE_LATITUDE + 0.006),
        area_stop(5, latitude=BASE_LATITUDE + 0.008),
        area_stop(6, latitude=BASE_LATITUDE + 0.010),
    ]

    result = group_area_visits(stops)

    assert [area.stop_ids for area in result.areas] == [
        ["stop-1", "stop-2", "stop-3", "stop-4", "stop-5", "stop-6"]
    ]
    assert result.areas[0].diameter_m > 1000
    assert result.areas[0].confidence >= 0.75


def test_minimum_size_area_gets_small_confidence_penalty() -> None:
    result = group_area_visits([area_stop(1), area_stop(2), area_stop(3)])

    assert [area.stop_ids for area in result.areas] == [["stop-1", "stop-2", "stop-3"]]
    assert result.areas[0].confidence == 0.9


def test_non_contiguous_stop_order_is_rejected() -> None:
    stops = [area_stop(1), area_stop(3), area_stop(4)]

    result = group_area_visits(stops)

    assert result.areas == []
    assert any(
        diagnostic.rejection_reason == AreaRejectionReason.NON_CONTIGUOUS_STOP_ORDER
        for diagnostic in result.diagnostics
    )


def test_input_stops_are_not_mutated() -> None:
    stops = [area_stop(index) for index in range(1, 5)]
    original = list(stops)

    group_area_visits(stops)

    assert stops == original


def test_repeated_execution_is_identical() -> None:
    stops = [area_stop(index) for index in range(1, 6)]

    first = group_area_visits(stops).to_dict()
    second = group_area_visits(stops).to_dict()

    assert first == second


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.executed = 0

    def scalar(self, statement: object) -> object | None:
        return None

    def add(self, record: object) -> None:
        self.added.append(record)

    def flush(self) -> None:
        for record in self.added:
            if isinstance(record, orm.AreaVisit) and record.id is None:
                record.id = uuid4()

    def execute(self, statement: object) -> None:
        self.executed += 1


def persisted_stop(stop_input: StopInput, trip_id: object, day_id: object) -> orm.Stop:
    return orm.Stop(
        id=uuid4(),
        trip_id=trip_id,
        trip_day_id=day_id,
        place_id=uuid4(),
        position=stop_input.sort_order,
        starts_at_utc=stop_input.start_time,
        ends_at_utc=stop_input.end_time,
    )


def test_persist_grouping_result_creates_area_and_membership_records() -> None:
    trip_id = uuid4()
    day_id = uuid4()
    run = orm.ReconstructionRun(
        id=uuid4(), trip_id=trip_id, algorithm_version="test", state="succeeded"
    )
    stop_inputs = [area_stop(index) for index in range(1, 4)]
    stops = [persisted_stop(stop_input, trip_id, day_id) for stop_input in stop_inputs]
    for stop_input, stop in zip(stop_inputs, stops, strict=True):
        stop_input_with_db_id = StopInput(
            id=str(stop.id),
            day_id=str(day_id),
            sort_order=stop_input.sort_order,
            start_time=stop_input.start_time,
            end_time=stop_input.end_time,
            latitude=stop_input.latitude,
            longitude=stop_input.longitude,
            location_confidence=stop_input.location_confidence,
        )
        stop_inputs[stop_input.sort_order - 1] = stop_input_with_db_id
    result = group_area_visits(stop_inputs)
    session = FakeSession()

    summary = persist_grouping_result(
        db=session,  # type: ignore[arg-type]
        trip_id=trip_id,
        day_id=day_id,
        run=run,
        result=result,
        stop_rows=[(stop, None, None) for stop in stops],
    )

    area_visits = [record for record in session.added if isinstance(record, orm.AreaVisit)]
    memberships = [record for record in session.added if isinstance(record, orm.AreaVisitStop)]
    assert session.executed == 2
    assert len(area_visits) == 1
    assert len(memberships) == 3
    assert area_visits[0].source == "automation"
    assert area_visits[0].algorithm_version == "area_visit_v1"
    assert cast(str, area_visits[0].center).startswith("SRID=4326;POINT(")
    assert [membership.sort_order for membership in memberships] == [1, 2, 3]
    assert {membership.reconstruction_run_id for membership in memberships} == {run.id}
    assert summary["persisted_area_visit_ids"] == [str(area_visits[0].id)]


def test_persist_grouping_result_flags_low_confidence_area_for_review() -> None:
    trip_id = uuid4()
    day_id = uuid4()
    run = orm.ReconstructionRun(
        id=uuid4(), trip_id=trip_id, algorithm_version="test", state="succeeded"
    )
    stop_inputs = [
        area_stop(1, minutes=0, latitude=35.0000, longitude=127.0),
        area_stop(2, minutes=43, latitude=35.0031, longitude=127.0),
        area_stop(3, minutes=86, latitude=35.0062, longitude=127.0),
    ]
    stops = [persisted_stop(stop_input, trip_id, day_id) for stop_input in stop_inputs]
    db_stop_inputs = [
        StopInput(
            id=str(stop.id),
            day_id=str(day_id),
            sort_order=stop_input.sort_order,
            start_time=stop_input.start_time,
            end_time=stop_input.end_time,
            latitude=stop_input.latitude,
            longitude=stop_input.longitude,
            location_confidence=stop_input.location_confidence,
        )
        for stop_input, stop in zip(stop_inputs, stops, strict=True)
    ]
    result = group_area_visits(db_stop_inputs)
    assert result.areas[0].confidence < 0.70
    session = FakeSession()

    summary = persist_grouping_result(
        db=session,  # type: ignore[arg-type]
        trip_id=trip_id,
        day_id=day_id,
        run=run,
        result=result,
        stop_rows=[(stop, None, None) for stop in stops],
    )

    review_items = [record for record in session.added if isinstance(record, orm.ReviewItem)]
    assert summary["area_review_count"] == 1
    assert len(review_items) == 1
    assert review_items[0].item_type == "possible_area_visit"
    assert review_items[0].target_type == "area_visit"
    assert review_items[0].media_item_id is None
    assert review_items[0].payload["stopCount"] == 3
