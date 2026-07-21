from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import ColumnElement, delete, exists, func, literal_column, or_, select, text
from sqlalchemy.orm import Session

from tripweave.adapters import orm
from tripweave.adapters.collaboration_intelligence import analyze_collaboration
from tripweave.domain.enums import (
    ProcessingState,
    ReconstructionRunState,
    ReconstructionSource,
    ReviewItemStatus,
    ReviewItemType,
    ReviewSeverity,
    RouteSource,
)
from tripweave.ports.geocoder import Geocoder

ALGORITHM_VERSION = "reconstruction_v1"
STOP_RADIUS_METERS = 150
STOP_GAP_MINUTES = 60
MOMENT_GAP_MINUTES = 15
MISSING_GPS_BRACKET_MINUTES = 30
MAX_IMPLIED_SPEED_KMH = 160
ALGORITHM_CONFIG: dict[str, object] = {
    "stop_radius_meters": STOP_RADIUS_METERS,
    "stop_gap_minutes": STOP_GAP_MINUTES,
    "moment_gap_minutes": MOMENT_GAP_MINUTES,
    "missing_gps_bracket_minutes": MISSING_GPS_BRACKET_MINUTES,
    "max_implied_speed_kmh": MAX_IMPLIED_SPEED_KMH,
}


@dataclass(frozen=True, slots=True)
class ReconstructionSummary:
    run_id: UUID
    days: int
    stops: int
    moments: int
    review_items: int


@dataclass(slots=True)
class MediaPoint:
    id: UUID
    contributor_member_id: UUID
    captured_at_utc: datetime | None
    original_local: datetime | None
    utc_offset_minutes: int | None
    latitude: float | None
    longitude: float | None
    location_confidence: float | None
    day: date | None = None
    stop: orm.Stop | None = None


@dataclass(slots=True)
class StopCluster:
    day: date
    media: list[MediaPoint]
    latitudes: list[float]
    longitudes: list[float]
    stop: orm.Stop | None = None

    @property
    def start(self) -> datetime:
        return min(point.captured_at_utc for point in self.media if point.captured_at_utc)

    @property
    def end(self) -> datetime:
        return max(point.captured_at_utc for point in self.media if point.captured_at_utc)

    @property
    def latitude(self) -> float:
        return sum(self.latitudes) / len(self.latitudes)

    @property
    def longitude(self) -> float:
        return sum(self.longitudes) / len(self.longitudes)


def reconstruct_trip(
    *,
    db: Session,
    trip: orm.Trip,
    geocoder: Geocoder,
) -> ReconstructionSummary:
    now = datetime.now(UTC)
    previous_run = latest_reconstruction_run(db, trip.id)
    run = orm.ReconstructionRun(
        trip_id=trip.id,
        state=ReconstructionRunState.RUNNING.value,
        source=ReconstructionSource.AUTOMATION.value,
        confidence=1.0,
        algorithm_version=ALGORITHM_VERSION,
        algorithm_config=ALGORITHM_CONFIG,
        user_locked=False,
        started_at=now,
    )
    db.add(run)
    db.flush()

    media_points = load_media_points(db, trip)
    usable: list[MediaPoint] = []
    missing_time: list[MediaPoint] = []
    for point in media_points:
        if point.captured_at_utc is None:
            missing_time.append(point)
            continue
        point.day = effective_day(trip, point)
        usable.append(point)

    unassigned_usable = unassigned_media_points(db, trip.id, usable)
    unassigned_missing_time = unassigned_media_points(db, trip.id, missing_time)
    if (
        previous_run is not None
        and has_visible_story(db, trip.id, previous_run)
        and (unassigned_usable or unassigned_missing_time)
    ):
        carry_forward_story(db, trip.id, previous_run, run)
        review_count = add_unknown_time_reviews(db, run, trip.id, unassigned_missing_time)
        summary = increment_story(
            db=db,
            run=run,
            trip=trip,
            usable=usable,
            geocoder=geocoder,
            base_review_count=review_count,
            unassigned=unassigned_usable,
        )
        db.commit()
        return summary

    delete_unlocked_outputs(db, trip.id)
    review_count = add_unknown_time_reviews(db, run, trip.id, missing_time)
    gps_points = [
        point for point in usable if point.latitude is not None and point.longitude is not None
    ]
    clusters = cluster_stops(gps_points)
    created = persist_clusters(db, run, trip.id, clusters, geocoder)
    review_count += assign_missing_gps(db, run, trip.id, usable, gps_points)
    moments = persist_moments(db, run, created, usable)
    legs = persist_legs(db, run, created, usable)
    merge_visible_trip_days_by_date(db, trip.id, run)
    merge_empty_locked_stops_with_generated_media(db, trip.id, run)
    intelligence = analyze_collaboration(db=db, trip_id=trip.id, run=run)
    review_count += intelligence.review_items

    run.state = ReconstructionRunState.SUCCEEDED.value
    run.finished_at = datetime.now(UTC)
    run.summary = {
        "days": len(created),
        "stops": sum(len(stops) for stops in created.values()),
        "moments": moments,
        "legs": legs,
        "similarityGroups": intelligence.similarity_groups,
        "clockOffsetSuggestions": intelligence.clock_suggestions,
        "reviewItems": review_count,
    }
    db.commit()
    return ReconstructionSummary(
        run_id=run.id,
        days=len(created),
        stops=sum(len(stops) for stops in created.values()),
        moments=moments,
        review_items=review_count,
    )


def latest_reconstruction_run(db: Session, trip_id: UUID) -> orm.ReconstructionRun | None:
    return db.execute(
        select(orm.ReconstructionRun)
        .where(
            orm.ReconstructionRun.trip_id == trip_id,
            orm.ReconstructionRun.state == ReconstructionRunState.SUCCEEDED.value,
        )
        .order_by(orm.ReconstructionRun.created_at.desc(), orm.ReconstructionRun.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def has_visible_story(db: Session, trip_id: UUID, run: orm.ReconstructionRun) -> bool:
    return (
        db.scalar(
            select(func.count())
            .select_from(orm.Stop)
            .where(
                orm.Stop.trip_id == trip_id,
                or_(
                    orm.Stop.reconstruction_run_id == run.id,
                    orm.Stop.user_locked.is_(True),
                ),
            )
        )
        or 0
    ) > 0


def carry_forward_story(
    db: Session,
    trip_id: UUID,
    previous_run: orm.ReconstructionRun,
    run: orm.ReconstructionRun,
) -> None:
    for model in (
        orm.TripDay,
        orm.Place,
        orm.Stop,
        orm.Moment,
        orm.MomentMedia,
        orm.MomentParticipant,
        orm.TripLeg,
        orm.ReviewItem,
    ):
        typed_model: Any = model
        rows = db.scalars(
            select(model).where(
                typed_model.trip_id == trip_id,
                typed_model.reconstruction_run_id == previous_run.id,
                typed_model.user_locked.is_(False),
            )
        )
        for row in rows:
            generated_row: Any = row
            generated_row.reconstruction_run_id = run.id
            generated_row.algorithm_version = ALGORITHM_VERSION


def increment_story(
    *,
    db: Session,
    run: orm.ReconstructionRun,
    trip: orm.Trip,
    usable: list[MediaPoint],
    geocoder: Geocoder,
    base_review_count: int,
    unassigned: list[MediaPoint],
) -> ReconstructionSummary:
    review_count = base_review_count
    changed_days: set[UUID] = set()
    added_stops = 0
    added_moments = 0
    assigned_media = 0
    for point in sorted(
        unassigned,
        key=lambda item: (item.captured_at_utc or datetime.min, item.id),
    ):
        assert point.captured_at_utc is not None
        if point.latitude is None or point.longitude is None:
            add_review_item(
                db,
                run,
                trip.id,
                point.id,
                ReviewItemType.UNKNOWN_LOCATION,
                "GPS is missing and cannot be incrementally placed without guessing.",
                severity=ReviewSeverity.MEDIUM,
                payload={"reason": "incremental_missing_location"},
            )
            review_count += 1
            continue
        stop = find_incremental_stop(db, trip.id, point)
        if stop is None:
            stop = create_incremental_stop(db, run, trip.id, point, geocoder)
            added_stops += 1
        else:
            stop.starts_at_utc = min(stop.starts_at_utc, point.captured_at_utc)
            stop.ends_at_utc = max(stop.ends_at_utc, point.captured_at_utc)
            stop.reconstruction_run_id = run.id
        point.stop = stop
        changed_days.add(stop.trip_day_id)
        moment, created = find_or_create_incremental_moment(db, run, stop, point)
        added_moments += int(created)
        add_media_to_moment(db, run, moment, point)
        assigned_media += 1

    for day_id in changed_days:
        renumber_day_stops(db, day_id)
        rebuild_day_legs(db, run, day_id)

    merge_visible_trip_days_by_date(db, trip.id, run)
    merge_empty_locked_stops_with_generated_media(db, trip.id, run)
    intelligence = analyze_collaboration(db=db, trip_id=trip.id, run=run)
    review_count += intelligence.review_items
    days = count_visible(db, orm.TripDay, trip.id, run.id)
    stops = count_visible(db, orm.Stop, trip.id, run.id)
    moments = count_visible(db, orm.Moment, trip.id, run.id)
    legs = count_visible(db, orm.TripLeg, trip.id, run.id)
    run.state = ReconstructionRunState.SUCCEEDED.value
    run.finished_at = datetime.now(UTC)
    run.summary = {
        "mode": "incremental",
        "days": days,
        "stops": stops,
        "moments": moments,
        "legs": legs,
        "newMedia": len(unassigned),
        "assignedMedia": assigned_media,
        "addedStops": added_stops,
        "addedMoments": added_moments,
        "similarityGroups": intelligence.similarity_groups,
        "clockOffsetSuggestions": intelligence.clock_suggestions,
        "reviewItems": review_count,
    }
    return ReconstructionSummary(
        run_id=run.id,
        days=days,
        stops=stops,
        moments=moments,
        review_items=review_count,
    )


def count_visible(db: Session, model: Any, trip_id: UUID, run_id: UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(model)
            .where(
                model.trip_id == trip_id,
                or_(model.reconstruction_run_id == run_id, model.user_locked.is_(True)),
            )
        )
        or 0
    )


def unassigned_media_points(
    db: Session, trip_id: UUID, usable: list[MediaPoint]
) -> list[MediaPoint]:
    assigned_ids = set(
        db.scalars(select(orm.MomentMedia.media_item_id).where(orm.MomentMedia.trip_id == trip_id))
    )
    reviewed_ids = set(
        db.scalars(
            select(orm.ReviewItem.media_item_id).where(
                orm.ReviewItem.trip_id == trip_id,
                orm.ReviewItem.media_item_id.is_not(None),
                orm.ReviewItem.status == ReviewItemStatus.OPEN.value,
            )
        )
    )
    return [
        point for point in usable if point.id not in assigned_ids and point.id not in reviewed_ids
    ]


def find_incremental_stop(db: Session, trip_id: UUID, point: MediaPoint) -> orm.Stop | None:
    assert point.day is not None
    assert point.captured_at_utc is not None
    assert point.latitude is not None and point.longitude is not None
    stop_lat: ColumnElement[float | None] = literal_column("ST_Y(stops.centroid::geometry)").label(
        "latitude"
    )
    stop_lon: ColumnElement[float | None] = literal_column("ST_X(stops.centroid::geometry)").label(
        "longitude"
    )
    rows = db.execute(
        select(orm.Stop, stop_lat, stop_lon)
        .join(orm.TripDay, orm.TripDay.id == orm.Stop.trip_day_id)
        .where(orm.Stop.trip_id == trip_id, orm.TripDay.day_date == point.day)
        .order_by(orm.Stop.starts_at_utc, orm.Stop.position)
    ).all()
    best: tuple[float, orm.Stop] | None = None
    for stop, latitude, longitude in rows:
        if latitude is None or longitude is None:
            continue
        gap_minutes = 0.0
        if point.captured_at_utc < stop.starts_at_utc:
            gap_minutes = (stop.starts_at_utc - point.captured_at_utc).total_seconds() / 60
        elif point.captured_at_utc > stop.ends_at_utc:
            gap_minutes = (point.captured_at_utc - stop.ends_at_utc).total_seconds() / 60
        if gap_minutes > STOP_GAP_MINUTES:
            continue
        distance = haversine_meters(
            float(latitude), float(longitude), point.latitude, point.longitude
        )
        if distance > STOP_RADIUS_METERS:
            continue
        if best is None or distance < best[0]:
            best = (distance, stop)
    return best[1] if best is not None else None


def create_incremental_stop(
    db: Session,
    run: orm.ReconstructionRun,
    trip_id: UUID,
    point: MediaPoint,
    geocoder: Geocoder,
) -> orm.Stop:
    assert point.day is not None
    assert point.captured_at_utc is not None
    assert point.latitude is not None and point.longitude is not None
    trip_day = find_or_create_trip_day(db, run, trip_id, point)
    geocode_result = geocoder.reverse_geocode(latitude=point.latitude, longitude=point.longitude)
    place = find_incremental_place(db, trip_id, point.latitude, point.longitude)
    if place is None:
        place = orm.Place(
            trip_id=trip_id,
            name=geocode_result.name,
            centroid=point_wkt(point.latitude, point.longitude),
            **generated(
                run,
                geocode_result.confidence
                if geocode_result.name is not None and geocode_result.confidence is not None
                else 0.9,
            ),
        )
        db.add(place)
        db.flush()
    elif place.name is None and geocode_result.name is not None and not place.user_locked:
        place.name = geocode_result.name
    stop = orm.Stop(
        trip_id=trip_id,
        trip_day_id=trip_day.id,
        place_id=place.id,
        title=geocode_result.name or place.name,
        position=next_stop_position(db, trip_day.id),
        starts_at_utc=point.captured_at_utc,
        ends_at_utc=point.captured_at_utc,
        centroid=point_wkt(point.latitude, point.longitude),
        **generated(run, 0.8),
    )
    db.add(stop)
    db.flush()
    return stop


def find_or_create_trip_day_for_date(
    db: Session,
    run: orm.ReconstructionRun,
    trip_id: UUID,
    day: date,
    starts_at_utc: datetime | None,
    ends_at_utc: datetime | None,
) -> orm.TripDay:
    existing = db.execute(
        select(orm.TripDay)
        .where(
            orm.TripDay.trip_id == trip_id,
            orm.TripDay.day_date == day,
            or_(
                orm.TripDay.reconstruction_run_id == run.id,
                orm.TripDay.user_locked.is_(True),
            ),
        )
        .order_by(orm.TripDay.user_locked.desc(), orm.TripDay.created_at)
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        if not existing.user_locked:
            existing.reconstruction_run_id = run.id
        if starts_at_utc is not None:
            existing.starts_at_utc = (
                min(existing.starts_at_utc, starts_at_utc)
                if existing.starts_at_utc is not None
                else starts_at_utc
            )
        if ends_at_utc is not None:
            existing.ends_at_utc = (
                max(existing.ends_at_utc, ends_at_utc)
                if existing.ends_at_utc is not None
                else ends_at_utc
            )
        return existing

    position = (
        db.scalar(
            select(func.count())
            .select_from(orm.TripDay)
            .where(
                orm.TripDay.trip_id == trip_id,
                or_(
                    orm.TripDay.reconstruction_run_id == run.id,
                    orm.TripDay.user_locked.is_(True),
                ),
            )
        )
        or 0
    ) + 1
    trip_day = orm.TripDay(
        trip_id=trip_id,
        day_date=day,
        position=position,
        starts_at_utc=starts_at_utc,
        ends_at_utc=ends_at_utc,
        **generated(run, 0.85),
    )
    db.add(trip_day)
    db.flush()
    renumber_visible_trip_days(db, trip_id, run.id)
    return trip_day


def find_or_create_trip_day(
    db: Session, run: orm.ReconstructionRun, trip_id: UUID, point: MediaPoint
) -> orm.TripDay:
    assert point.day is not None
    return find_or_create_trip_day_for_date(
        db,
        run,
        trip_id,
        point.day,
        point.captured_at_utc,
        point.captured_at_utc,
    )


def find_incremental_place(
    db: Session, trip_id: UUID, latitude: float, longitude: float
) -> orm.Place | None:
    place_lat: ColumnElement[float | None] = literal_column(
        "ST_Y(places.centroid::geometry)"
    ).label("latitude")
    place_lon: ColumnElement[float | None] = literal_column(
        "ST_X(places.centroid::geometry)"
    ).label("longitude")
    rows = db.execute(
        select(orm.Place, place_lat, place_lon).where(orm.Place.trip_id == trip_id)
    ).all()
    best: tuple[float, orm.Place] | None = None
    for place, place_latitude, place_longitude in rows:
        if place_latitude is None or place_longitude is None:
            continue
        distance = haversine_meters(
            float(place_latitude), float(place_longitude), latitude, longitude
        )
        if distance > STOP_RADIUS_METERS:
            continue
        if best is None or distance < best[0]:
            best = (distance, place)
    return best[1] if best is not None else None


def next_stop_position(db: Session, trip_day_id: UUID) -> int:
    return (
        db.scalar(select(func.max(orm.Stop.position)).where(orm.Stop.trip_day_id == trip_day_id))
        or 0
    ) + 1


def find_or_create_incremental_moment(
    db: Session, run: orm.ReconstructionRun, stop: orm.Stop, point: MediaPoint
) -> tuple[orm.Moment, bool]:
    assert point.captured_at_utc is not None
    moments = list(
        db.scalars(
            select(orm.Moment)
            .where(orm.Moment.stop_id == stop.id)
            .order_by(orm.Moment.starts_at_utc, orm.Moment.position)
        )
    )
    best: tuple[float, orm.Moment] | None = None
    for moment in moments:
        gap_minutes = 0.0
        if point.captured_at_utc < moment.starts_at_utc:
            gap_minutes = (moment.starts_at_utc - point.captured_at_utc).total_seconds() / 60
        elif point.captured_at_utc > moment.ends_at_utc:
            gap_minutes = (point.captured_at_utc - moment.ends_at_utc).total_seconds() / 60
        if gap_minutes > MOMENT_GAP_MINUTES:
            continue
        if best is None or gap_minutes < best[0]:
            best = (gap_minutes, moment)
    if best is not None:
        moment = best[1]
        moment.starts_at_utc = min(moment.starts_at_utc, point.captured_at_utc)
        moment.ends_at_utc = max(moment.ends_at_utc, point.captured_at_utc)
        moment.reconstruction_run_id = run.id
        return moment, False

    moment = orm.Moment(
        trip_id=stop.trip_id,
        stop_id=stop.id,
        position=(max((item.position for item in moments), default=0) + 1),
        starts_at_utc=point.captured_at_utc,
        ends_at_utc=point.captured_at_utc,
        **generated(run, 0.8),
    )
    db.add(moment)
    db.flush()
    renumber_stop_moments(db, stop.id)
    return moment, True


def add_media_to_moment(
    db: Session, run: orm.ReconstructionRun, moment: orm.Moment, point: MediaPoint
) -> None:
    existing = db.execute(
        select(orm.MomentMedia).where(
            orm.MomentMedia.moment_id == moment.id,
            orm.MomentMedia.media_item_id == point.id,
        )
    ).scalar_one_or_none()
    if existing is None:
        position = (
            db.scalar(
                select(func.max(orm.MomentMedia.position)).where(
                    orm.MomentMedia.moment_id == moment.id
                )
            )
            or 0
        ) + 1
        db.add(
            orm.MomentMedia(
                trip_id=moment.trip_id,
                moment_id=moment.id,
                media_item_id=point.id,
                position=position,
                **generated(run, 0.8),
            )
        )
        db.flush()
    participant = db.execute(
        select(orm.MomentParticipant).where(
            orm.MomentParticipant.moment_id == moment.id,
            orm.MomentParticipant.trip_member_id == point.contributor_member_id,
        )
    ).scalar_one_or_none()
    if participant is None:
        db.add(
            orm.MomentParticipant(
                trip_id=moment.trip_id,
                moment_id=moment.id,
                trip_member_id=point.contributor_member_id,
                **generated(run, 0.8),
            )
        )
        db.flush()


def renumber_visible_trip_days(db: Session, trip_id: UUID, run_id: UUID) -> None:
    days = list(
        db.scalars(
            select(orm.TripDay)
            .where(
                orm.TripDay.trip_id == trip_id,
                or_(
                    orm.TripDay.reconstruction_run_id == run_id,
                    orm.TripDay.user_locked.is_(True),
                ),
            )
            .order_by(orm.TripDay.day_date, orm.TripDay.starts_at_utc, orm.TripDay.position)
        )
    )
    for position, day in enumerate(days, start=1):
        day.position = position


def merge_visible_trip_days_by_date(db: Session, trip_id: UUID, run: orm.ReconstructionRun) -> None:
    days = list(
        db.scalars(
            select(orm.TripDay)
            .where(
                orm.TripDay.trip_id == trip_id,
                or_(
                    orm.TripDay.reconstruction_run_id == run.id,
                    orm.TripDay.user_locked.is_(True),
                ),
            )
            .order_by(
                orm.TripDay.day_date,
                orm.TripDay.user_locked.desc(),
                orm.TripDay.starts_at_utc,
                orm.TripDay.created_at,
            )
        )
    )
    days_by_date: dict[date, list[orm.TripDay]] = defaultdict(list)
    for day in days:
        days_by_date[day.day_date].append(day)

    changed_day_ids: set[UUID] = set()
    for duplicate_days in days_by_date.values():
        if len(duplicate_days) < 2:
            continue
        canonical = duplicate_days[0]
        changed_day_ids.add(canonical.id)
        for duplicate in duplicate_days[1:]:
            canonical_stops = list(
                db.scalars(
                    select(orm.Stop)
                    .where(orm.Stop.trip_day_id == canonical.id)
                    .order_by(orm.Stop.position, orm.Stop.starts_at_utc, orm.Stop.id)
                )
            )
            duplicate_stops = list(
                db.scalars(
                    select(orm.Stop)
                    .where(orm.Stop.trip_day_id == duplicate.id)
                    .order_by(orm.Stop.position, orm.Stop.starts_at_utc, orm.Stop.id)
                )
            )
            for stop in duplicate_stops:
                target_stop = next(
                    (
                        candidate
                        for candidate in canonical_stops
                        if candidate.position == stop.position
                    ),
                    None,
                )
                if target_stop is None:
                    stop.trip_day_id = canonical.id
                    canonical_stops.append(stop)
                    continue
                if not target_stop.title and stop.title:
                    target_stop.title = stop.title
                if not target_stop.note and stop.note:
                    target_stop.note = stop.note
                target_stop.starts_at_utc = min(target_stop.starts_at_utc, stop.starts_at_utc)
                target_stop.ends_at_utc = max(target_stop.ends_at_utc, stop.ends_at_utc)
                moments = list(db.scalars(select(orm.Moment).where(orm.Moment.stop_id == stop.id)))
                for moment in moments:
                    moment.stop_id = target_stop.id
                db.delete(stop)
            duplicate_legs = list(
                db.scalars(select(orm.TripLeg).where(orm.TripLeg.trip_day_id == duplicate.id))
            )
            for leg in duplicate_legs:
                db.delete(leg)
            if not canonical.title and duplicate.title:
                canonical.title = duplicate.title
            if not canonical.note and duplicate.note:
                canonical.note = duplicate.note
            if duplicate.starts_at_utc is not None:
                canonical.starts_at_utc = (
                    min(canonical.starts_at_utc, duplicate.starts_at_utc)
                    if canonical.starts_at_utc is not None
                    else duplicate.starts_at_utc
                )
            if duplicate.ends_at_utc is not None:
                canonical.ends_at_utc = (
                    max(canonical.ends_at_utc, duplicate.ends_at_utc)
                    if canonical.ends_at_utc is not None
                    else duplicate.ends_at_utc
                )
            db.delete(duplicate)
        db.flush()

    for day_id in changed_day_ids:
        renumber_day_stops(db, day_id)
        for stop in db.scalars(select(orm.Stop).where(orm.Stop.trip_day_id == day_id)):
            renumber_stop_moments(db, stop.id)
        rebuild_day_legs(db, run, day_id)
    renumber_visible_trip_days(db, trip_id, run.id)


def merge_empty_locked_stops_with_generated_media(
    db: Session, trip_id: UUID, run: orm.ReconstructionRun
) -> None:
    days = list(
        db.scalars(
            select(orm.TripDay)
            .where(
                orm.TripDay.trip_id == trip_id,
                or_(
                    orm.TripDay.reconstruction_run_id == run.id,
                    orm.TripDay.user_locked.is_(True),
                ),
            )
            .order_by(orm.TripDay.day_date, orm.TripDay.position)
        )
    )
    changed_day_ids: set[UUID] = set()
    for day in days:
        stops = list(
            db.scalars(
                select(orm.Stop)
                .where(orm.Stop.trip_day_id == day.id)
                .order_by(orm.Stop.starts_at_utc, orm.Stop.position, orm.Stop.id)
            )
        )
        locked_targets = [
            stop for stop in stops if stop.user_locked and stop_media_count(db, stop.id) == 0
        ]
        generated_sources = [
            stop
            for stop in stops
            if not stop.user_locked
            and stop.reconstruction_run_id == run.id
            and stop_media_count(db, stop.id) > 0
        ]
        for source in generated_sources:
            target = best_empty_locked_stop_target(db, locked_targets, source)
            if target is None:
                continue
            merge_stop_into_target(db, source, target)
            changed_day_ids.add(day.id)

    for day_id in changed_day_ids:
        renumber_day_stops(db, day_id)
        for stop in db.scalars(select(orm.Stop).where(orm.Stop.trip_day_id == day_id)):
            renumber_stop_moments(db, stop.id)
        rebuild_day_legs(db, run, day_id)


def best_empty_locked_stop_target(
    db: Session, targets: list[orm.Stop], source: orm.Stop
) -> orm.Stop | None:
    source_latitude, source_longitude = stop_coordinates(db, source.id)
    if source_latitude is None or source_longitude is None:
        return None
    best: tuple[float, orm.Stop] | None = None
    for target in targets:
        if not stop_time_ranges_touch(target, source):
            continue
        target_latitude, target_longitude = stop_coordinates(db, target.id)
        if target_latitude is None or target_longitude is None:
            continue
        distance = haversine_meters(
            target_latitude,
            target_longitude,
            source_latitude,
            source_longitude,
        )
        if distance > STOP_RADIUS_METERS:
            continue
        if best is None or distance < best[0]:
            best = (distance, target)
    return best[1] if best is not None else None


def merge_stop_into_target(db: Session, source: orm.Stop, target: orm.Stop) -> None:
    if not target.title and source.title:
        target.title = source.title
    if not target.note and source.note:
        target.note = source.note
    target.starts_at_utc = min(target.starts_at_utc, source.starts_at_utc)
    target.ends_at_utc = max(target.ends_at_utc, source.ends_at_utc)
    moments = list(db.scalars(select(orm.Moment).where(orm.Moment.stop_id == source.id)))
    for moment in moments:
        moment.stop_id = target.id
    db.execute(delete(orm.TripLeg).where(orm.TripLeg.from_stop_id == source.id))
    db.execute(delete(orm.TripLeg).where(orm.TripLeg.to_stop_id == source.id))
    db.delete(source)
    db.flush()


def stop_media_count(db: Session, stop_id: UUID) -> int:
    return (
        db.scalar(
            select(func.count(orm.MomentMedia.id))
            .join(orm.Moment, orm.Moment.id == orm.MomentMedia.moment_id)
            .where(orm.Moment.stop_id == stop_id)
        )
        or 0
    )


def stop_coordinates(db: Session, stop_id: UUID) -> tuple[float | None, float | None]:
    latitude: Any = literal_column("ST_Y(stops.centroid::geometry)").label("latitude")
    longitude: Any = literal_column("ST_X(stops.centroid::geometry)").label("longitude")
    row = db.execute(
        select(latitude, longitude).select_from(orm.Stop).where(orm.Stop.id == stop_id)
    ).one_or_none()
    if row is None:
        return None, None
    return (
        float(row.latitude) if row.latitude is not None else None,
        float(row.longitude) if row.longitude is not None else None,
    )


def stop_time_ranges_touch(target: orm.Stop, source: orm.Stop) -> bool:
    return source.starts_at_utc <= target.ends_at_utc + timedelta(
        minutes=MOMENT_GAP_MINUTES
    ) and source.ends_at_utc >= target.starts_at_utc - timedelta(minutes=MOMENT_GAP_MINUTES)


def renumber_day_stops(db: Session, trip_day_id: UUID) -> None:
    stops = list(
        db.scalars(
            select(orm.Stop)
            .where(orm.Stop.trip_day_id == trip_day_id)
            .order_by(orm.Stop.starts_at_utc, orm.Stop.ends_at_utc, orm.Stop.position, orm.Stop.id)
        )
    )
    for position, stop in enumerate(stops, start=1):
        stop.position = position


def renumber_stop_moments(db: Session, stop_id: UUID) -> None:
    moments = list(
        db.scalars(
            select(orm.Moment)
            .where(orm.Moment.stop_id == stop_id)
            .order_by(
                orm.Moment.starts_at_utc,
                orm.Moment.ends_at_utc,
                orm.Moment.position,
                orm.Moment.id,
            )
        )
    )
    for position, moment in enumerate(moments, start=1):
        moment.position = position


def rebuild_day_legs(db: Session, run: orm.ReconstructionRun, trip_day_id: UUID) -> None:
    db.execute(
        delete(orm.TripLeg).where(
            orm.TripLeg.trip_day_id == trip_day_id,
            orm.TripLeg.user_locked.is_(False),
        )
    )
    trip_day = db.get(orm.TripDay, trip_day_id)
    if trip_day is None:
        return

    for from_stop_id, to_stop_id in continuity_edges_for_day(db, trip_day_id):
        db.add(
            orm.TripLeg(
                trip_id=trip_day.trip_id,
                trip_day_id=trip_day.id,
                from_stop_id=from_stop_id,
                to_stop_id=to_stop_id,
                route_source=RouteSource.PHOTO_INFERRED.value,
                geometry=line_between_stops_wkt(db, from_stop_id, to_stop_id),
                **generated(run, 0.7),
            )
        )


def line_between_stops_wkt(db: Session, from_stop_id: UUID, to_stop_id: UUID) -> str | None:
    return db.execute(
        text(
            """
            SELECT ST_AsEWKT(ST_MakeLine(source.centroid::geometry, target.centroid::geometry))
            FROM stops source, stops target
            WHERE source.id = CAST(:from_stop_id AS uuid)
                AND target.id = CAST(:to_stop_id AS uuid)
            """
        ),
        {"from_stop_id": str(from_stop_id), "to_stop_id": str(to_stop_id)},
    ).scalar_one_or_none()


def delete_unlocked_outputs(db: Session, trip_id: UUID) -> None:
    for model in (
        orm.ReviewItem,
        orm.TripLeg,
        orm.MomentParticipant,
        orm.MomentMedia,
        orm.Moment,
        orm.Stop,
    ):
        db.execute(delete(model).where(model.trip_id == trip_id, model.user_locked.is_(False)))
    db.execute(
        delete(orm.Place).where(
            orm.Place.trip_id == trip_id,
            orm.Place.user_locked.is_(False),
            ~exists().where(orm.Stop.place_id == orm.Place.id),
        )
    )
    db.execute(
        delete(orm.TripDay).where(
            orm.TripDay.trip_id == trip_id,
            orm.TripDay.user_locked.is_(False),
            ~exists().where(orm.Stop.trip_day_id == orm.TripDay.id),
            ~exists().where(orm.TripLeg.trip_day_id == orm.TripDay.id),
        )
    )


def load_media_points(db: Session, trip: orm.Trip) -> list[MediaPoint]:
    lat: ColumnElement[float | None] = literal_column(
        "ST_Y(media_items.effective_location::geometry)"
    ).label("latitude")
    lon: ColumnElement[float | None] = literal_column(
        "ST_X(media_items.effective_location::geometry)"
    ).label("longitude")
    rows = db.execute(
        select(orm.MediaItem, lat, lon)
        .where(
            orm.MediaItem.trip_id == trip.id,
            orm.MediaItem.deleted_at.is_(None),
            orm.MediaItem.processing_state == ProcessingState.READY.value,
        )
        .order_by(
            orm.MediaItem.effective_captured_at_utc, orm.MediaItem.created_at, orm.MediaItem.id
        )
    ).all()
    points: list[MediaPoint] = []
    for media, latitude, longitude in rows:
        points.append(
            MediaPoint(
                id=media.id,
                contributor_member_id=media.contributor_member_id,
                captured_at_utc=media_capture_utc(trip, media),
                original_local=media.original_captured_at_local,
                utc_offset_minutes=media.original_utc_offset_minutes,
                latitude=float(latitude) if latitude is not None else None,
                longitude=float(longitude) if longitude is not None else None,
                location_confidence=media.location_confidence,
            )
        )
    return points


def effective_day(trip: orm.Trip, point: MediaPoint) -> date:
    assert point.captured_at_utc is not None
    if point.utc_offset_minutes is not None:
        local_time = (point.captured_at_utc + timedelta(minutes=point.utc_offset_minutes)).replace(
            tzinfo=None
        )
    else:
        try:
            local_time = point.captured_at_utc.astimezone(ZoneInfo(trip.timezone_id)).replace(
                tzinfo=None
            )
        except ZoneInfoNotFoundError:
            local_time = point.captured_at_utc.astimezone(UTC).replace(tzinfo=None)
    return (local_time - timedelta(hours=trip.day_cutoff_hour)).date()


def media_capture_utc(trip: orm.Trip, media: orm.MediaItem) -> datetime | None:
    known_utc = media.effective_captured_at_utc or media.original_captured_at_utc
    if known_utc is not None:
        return known_utc
    if media.original_captured_at_local is None:
        return None
    if media.original_utc_offset_minutes is not None:
        tz = UTC
        return (
            media.original_captured_at_local - timedelta(minutes=media.original_utc_offset_minutes)
        ).replace(tzinfo=tz)
    try:
        localized = media.original_captured_at_local.replace(tzinfo=ZoneInfo(trip.timezone_id))
    except ZoneInfoNotFoundError:
        localized = media.original_captured_at_local.replace(tzinfo=UTC)
    return localized.astimezone(UTC)


def cluster_stops(points: list[MediaPoint]) -> dict[date, list[StopCluster]]:
    grouped: dict[date, list[MediaPoint]] = defaultdict(list)
    for point in points:
        if point.day is not None:
            grouped[point.day].append(point)

    clusters_by_day: dict[date, list[StopCluster]] = {}
    for day, day_points in grouped.items():
        clusters: list[StopCluster] = []
        current: StopCluster | None = None
        previous: MediaPoint | None = None
        for point in sorted(
            day_points, key=lambda item: (item.captured_at_utc or datetime.min, item.id)
        ):
            assert point.captured_at_utc is not None
            assert point.latitude is not None and point.longitude is not None
            starts_new = current is None
            if current is not None and previous is not None and previous.captured_at_utc:
                gap_minutes = (
                    point.captured_at_utc - previous.captured_at_utc
                ).total_seconds() / 60
                distance_m = haversine_meters(
                    current.latitude, current.longitude, point.latitude, point.longitude
                )
                speed_kmh = implied_speed_kmh(
                    previous.latitude,
                    previous.longitude,
                    point.latitude,
                    point.longitude,
                    gap_minutes,
                )
                starts_new = (
                    gap_minutes > STOP_GAP_MINUTES
                    or distance_m > STOP_RADIUS_METERS
                    or speed_kmh > MAX_IMPLIED_SPEED_KMH
                )
            if starts_new:
                current = StopCluster(day=day, media=[], latitudes=[], longitudes=[])
                clusters.append(current)
            assert current is not None
            current.media.append(point)
            current.latitudes.append(point.latitude)
            current.longitudes.append(point.longitude)
            previous = point
        clusters_by_day[day] = clusters
    return clusters_by_day


def persist_clusters(
    db: Session,
    run: orm.ReconstructionRun,
    trip_id: UUID,
    clusters_by_day: dict[date, list[StopCluster]],
    geocoder: Geocoder,
) -> dict[orm.TripDay, list[orm.Stop]]:
    created: dict[orm.TripDay, list[orm.Stop]] = {}
    known_places: list[tuple[orm.Place, float, float]] = []
    for day in sorted(clusters_by_day):
        clusters = clusters_by_day[day]
        trip_day = find_or_create_trip_day_for_date(
            db,
            run,
            trip_id,
            day,
            min(cluster.start for cluster in clusters) if clusters else None,
            max(cluster.end for cluster in clusters) if clusters else None,
        )
        stops: list[orm.Stop] = []
        for stop_position, cluster in enumerate(clusters, start=1):
            geocode_result = geocoder.reverse_geocode(
                latitude=cluster.latitude, longitude=cluster.longitude
            )
            place = find_place(known_places, cluster.latitude, cluster.longitude)
            if place is None:
                name = geocode_result.name
                place = orm.Place(
                    trip_id=trip_id,
                    name=name,
                    centroid=point_wkt(cluster.latitude, cluster.longitude),
                    **generated(
                        run,
                        geocode_result.confidence
                        if name is not None and geocode_result.confidence is not None
                        else 0.9,
                    ),
                )
                db.add(place)
                db.flush()
                known_places.append((place, cluster.latitude, cluster.longitude))
            elif place.name is None and geocode_result.name is not None and not place.user_locked:
                place.name = geocode_result.name
            stop = orm.Stop(
                trip_id=trip_id,
                trip_day_id=trip_day.id,
                place_id=place.id,
                title=geocode_result.name or place.name,
                position=stop_position,
                starts_at_utc=cluster.start,
                ends_at_utc=cluster.end,
                centroid=point_wkt(cluster.latitude, cluster.longitude),
                **generated(run, 0.9),
            )
            db.add(stop)
            db.flush()
            for point in cluster.media:
                point.stop = stop
            cluster.stop = stop
            stops.append(stop)
        created[trip_day] = stops
    return created


def assign_missing_gps(
    db: Session,
    run: orm.ReconstructionRun,
    trip_id: UUID,
    usable: list[MediaPoint],
    gps_points: list[MediaPoint],
) -> int:
    review_count = 0
    sorted_gps = sorted(gps_points, key=lambda point: point.captured_at_utc or datetime.min)
    for point in usable:
        if point.latitude is not None or point.longitude is not None:
            continue
        previous = next(
            (
                candidate
                for candidate in reversed(sorted_gps)
                if candidate.captured_at_utc is not None
                and point.captured_at_utc is not None
                and candidate.captured_at_utc < point.captured_at_utc
            ),
            None,
        )
        following = next(
            (
                candidate
                for candidate in sorted_gps
                if candidate.captured_at_utc is not None
                and point.captured_at_utc is not None
                and candidate.captured_at_utc > point.captured_at_utc
            ),
            None,
        )
        if (
            point.captured_at_utc is not None
            and previous is not None
            and following is not None
            and previous.captured_at_utc is not None
            and following.captured_at_utc is not None
            and previous.stop is not None
            and previous.stop == following.stop
            and previous.location_confidence is not None
            and following.location_confidence is not None
            and previous.location_confidence >= 0.8
            and following.location_confidence >= 0.8
            and (point.captured_at_utc - previous.captured_at_utc).total_seconds() / 60
            <= MISSING_GPS_BRACKET_MINUTES
            and (following.captured_at_utc - point.captured_at_utc).total_seconds() / 60
            <= MISSING_GPS_BRACKET_MINUTES
        ):
            point.stop = previous.stop
            continue
        add_review_item(
            db,
            run,
            trip_id,
            point.id,
            ReviewItemType.UNKNOWN_LOCATION,
            "GPS is missing and cannot be assigned without guessing.",
            severity=ReviewSeverity.MEDIUM,
            payload={"reason": "not_bracketed_by_same_high_confidence_stop"},
        )
        review_count += 1
    return review_count


def persist_moments(
    db: Session,
    run: orm.ReconstructionRun,
    created: dict[orm.TripDay, list[orm.Stop]],
    usable: list[MediaPoint],
) -> int:
    moment_count = 0
    for stops in created.values():
        for stop in stops:
            media = [
                point
                for point in usable
                if point.captured_at_utc is not None and point.stop == stop
            ]
            groups = split_moments(media)
            for position, group in enumerate(groups, start=1):
                moment = orm.Moment(
                    trip_id=stop.trip_id,
                    stop_id=stop.id,
                    position=position,
                    starts_at_utc=min(
                        point.captured_at_utc for point in group if point.captured_at_utc
                    ),
                    ends_at_utc=max(
                        point.captured_at_utc for point in group if point.captured_at_utc
                    ),
                    **generated(run, 0.85),
                )
                db.add(moment)
                db.flush()
                for media_position, point in enumerate(group, start=1):
                    db.add(
                        orm.MomentMedia(
                            trip_id=stop.trip_id,
                            moment_id=moment.id,
                            media_item_id=point.id,
                            position=media_position,
                            **generated(run, 0.85),
                        )
                    )
                for participant_id in sorted({point.contributor_member_id for point in group}):
                    db.add(
                        orm.MomentParticipant(
                            trip_id=stop.trip_id,
                            moment_id=moment.id,
                            trip_member_id=participant_id,
                            **generated(run, 0.85),
                        )
                    )
                moment_count += 1
    return moment_count


def split_moments(media: list[MediaPoint]) -> list[list[MediaPoint]]:
    groups: list[list[MediaPoint]] = []
    current: list[MediaPoint] = []
    previous: MediaPoint | None = None
    for point in sorted(media, key=lambda item: (item.captured_at_utc or datetime.min, item.id)):
        assert point.captured_at_utc is not None
        if previous is not None and previous.captured_at_utc is not None:
            gap = (point.captured_at_utc - previous.captured_at_utc).total_seconds() / 60
            if gap > MOMENT_GAP_MINUTES:
                groups.append(current)
                current = []
        current.append(point)
        previous = point
    if current:
        groups.append(current)
    return groups


def persist_legs(
    db: Session,
    run: orm.ReconstructionRun,
    created: dict[orm.TripDay, list[orm.Stop]],
    usable: list[MediaPoint],
) -> int:
    count = 0
    for trip_day, stops in created.items():
        stop_by_id = {stop.id: stop for stop in stops}
        for from_stop_id, to_stop_id in continuity_edges_for_points(
            [point for point in usable if point.day == trip_day.day_date],
            stops,
        ):
            previous = stop_by_id.get(from_stop_id)
            current = stop_by_id.get(to_stop_id)
            if previous is None or current is None:
                continue
            db.add(
                orm.TripLeg(
                    trip_id=trip_day.trip_id,
                    trip_day_id=trip_day.id,
                    from_stop_id=previous.id,
                    to_stop_id=current.id,
                    route_source=RouteSource.PHOTO_INFERRED.value,
                    geometry=line_wkt(previous.centroid, current.centroid),
                    **generated(run, 0.7),
                )
            )
            count += 1
    return count


def continuity_edges_for_points(
    points: list[MediaPoint], stops: list[orm.Stop]
) -> list[tuple[UUID, UUID]]:
    return continuity_edges_for_stops(
        stops=stops,
        observed_edges=observed_contributor_edges_for_points(points),
    )


def observed_contributor_edges_for_points(points: list[MediaPoint]) -> list[tuple[UUID, UUID]]:
    by_contributor: dict[UUID, list[MediaPoint]] = defaultdict(list)
    for point in points:
        if point.stop is not None and point.captured_at_utc is not None:
            by_contributor[point.contributor_member_id].append(point)

    edges: set[tuple[UUID, UUID]] = set()
    ordered_edges: list[tuple[UUID, UUID]] = []
    for contributor_points in by_contributor.values():
        previous_stop_id: UUID | None = None
        for point in sorted(
            contributor_points, key=lambda item: (item.captured_at_utc or datetime.min, item.id)
        ):
            assert point.stop is not None
            current_stop_id = point.stop.id
            if previous_stop_id is not None and previous_stop_id != current_stop_id:
                edge = (previous_stop_id, current_stop_id)
                if edge not in edges:
                    edges.add(edge)
                    ordered_edges.append(edge)
            previous_stop_id = current_stop_id
    return ordered_edges


def continuity_edges_for_day(db: Session, trip_day_id: UUID) -> list[tuple[UUID, UUID]]:
    stops = list(
        db.scalars(
            select(orm.Stop)
            .where(orm.Stop.trip_day_id == trip_day_id)
            .order_by(orm.Stop.starts_at_utc, orm.Stop.ends_at_utc, orm.Stop.position, orm.Stop.id)
        )
    )
    return continuity_edges_for_stops(
        stops=stops,
        observed_edges=observed_contributor_edges_for_day(db, trip_day_id),
    )


def observed_contributor_edges_for_day(db: Session, trip_day_id: UUID) -> list[tuple[UUID, UUID]]:
    rows = db.execute(
        select(
            orm.MediaItem.contributor_member_id,
            orm.Moment.stop_id,
            orm.MediaItem.effective_captured_at_utc,
            orm.MediaItem.original_captured_at_utc,
            orm.MediaItem.original_captured_at_local,
            orm.MediaItem.created_at,
            orm.MediaItem.id,
        )
        .join(orm.MomentMedia, orm.MomentMedia.media_item_id == orm.MediaItem.id)
        .join(orm.Moment, orm.Moment.id == orm.MomentMedia.moment_id)
        .join(orm.Stop, orm.Stop.id == orm.Moment.stop_id)
        .where(orm.Stop.trip_day_id == trip_day_id)
        .order_by(
            orm.MediaItem.contributor_member_id,
            orm.MediaItem.effective_captured_at_utc,
            orm.MediaItem.original_captured_at_utc,
            orm.MediaItem.original_captured_at_local,
            orm.MediaItem.created_at,
            orm.MediaItem.id,
        )
    ).all()
    by_contributor: dict[UUID, list[tuple[datetime | None, UUID, UUID]]] = defaultdict(list)
    for (
        contributor_id,
        stop_id,
        effective_captured_at,
        original_captured_at,
        original_local,
        created_at,
        media_id,
    ) in rows:
        captured_at = effective_captured_at or original_captured_at or original_local or created_at
        by_contributor[contributor_id].append((captured_at, media_id, stop_id))

    edges: set[tuple[UUID, UUID]] = set()
    ordered_edges: list[tuple[UUID, UUID]] = []
    for contributor_rows in by_contributor.values():
        previous_stop_id: UUID | None = None
        for _, _, stop_id in sorted(
            contributor_rows,
            key=lambda item: (datetime_sort_key(item[0]), item[1]),
        ):
            if previous_stop_id is not None and previous_stop_id != stop_id:
                edge = (previous_stop_id, stop_id)
                if edge not in edges:
                    edges.add(edge)
                    ordered_edges.append(edge)
            previous_stop_id = stop_id
    return ordered_edges


def continuity_edges_for_stops(
    *, stops: list[orm.Stop], observed_edges: list[tuple[UUID, UUID]]
) -> list[tuple[UUID, UUID]]:
    ordered_stops = sorted(
        stops,
        key=lambda stop: (
            stop.starts_at_utc,
            stop.ends_at_utc,
            stop.position,
            stop.id,
        ),
    )
    if not ordered_stops:
        return []

    rank_by_stop_id = stop_ranks(ordered_stops, observed_edges)
    stops_by_rank: dict[int, list[orm.Stop]] = defaultdict(list)
    for stop in ordered_stops:
        stops_by_rank[rank_by_stop_id.get(stop.id, stop.position)].append(stop)
    for rank_stops in stops_by_rank.values():
        rank_stops.sort(
            key=lambda stop: (
                stop.starts_at_utc,
                stop.ends_at_utc,
                stop.position,
                stop.id,
            )
        )

    edges: set[tuple[UUID, UUID]] = set()
    ordered_edges: list[tuple[UUID, UUID]] = []

    def add_edge(from_stop_id: UUID, to_stop_id: UUID) -> None:
        if from_stop_id == to_stop_id:
            return
        edge = (from_stop_id, to_stop_id)
        if edge not in edges:
            edges.add(edge)
            ordered_edges.append(edge)

    for from_stop_id, to_stop_id in observed_edges:
        from_rank = rank_by_stop_id.get(from_stop_id)
        to_rank = rank_by_stop_id.get(to_stop_id)
        if from_rank is None or to_rank is None or to_rank <= from_rank + 1:
            add_edge(from_stop_id, to_stop_id)
            continue
        path = [from_stop_id]
        for rank in range(from_rank + 1, to_rank):
            next_stop = stops_by_rank.get(rank, [None])[0]
            if next_stop is not None:
                path.append(next_stop.id)
        path.append(to_stop_id)
        for previous_stop_id, current_stop_id in zip(path, path[1:], strict=False):
            add_edge(previous_stop_id, current_stop_id)

    outgoing_stop_ids = {from_stop_id for from_stop_id, _ in ordered_edges}
    ranks = sorted(stops_by_rank)
    rank_index_by_value = {rank: index for index, rank in enumerate(ranks)}
    for stop in ordered_stops:
        if stop.id in outgoing_stop_ids:
            continue
        rank = rank_by_stop_id.get(stop.id, stop.position)
        next_rank_index = rank_index_by_value.get(rank, -1) + 1
        if next_rank_index <= 0 or next_rank_index >= len(ranks):
            continue
        next_stop = stops_by_rank[ranks[next_rank_index]][0]
        add_edge(stop.id, next_stop.id)

    return ordered_edges


def stop_ranks(stops: list[orm.Stop], edges: list[tuple[UUID, UUID]]) -> dict[UUID, int]:
    if not edges:
        return {stop.id: index for index, stop in enumerate(stops, start=1)}

    stop_ids = {stop.id for stop in stops}
    parent_ids: dict[UUID, set[UUID]] = {stop.id: set() for stop in stops}
    for from_stop_id, to_stop_id in edges:
        if from_stop_id in stop_ids and to_stop_id in stop_ids:
            parent_ids[to_stop_id].add(from_stop_id)

    rank_by_stop_id: dict[UUID, int] = {}
    remaining = set(stop_ids)
    while remaining:
        progressed = False
        for stop in stops:
            if stop.id not in remaining:
                continue
            parents = parent_ids[stop.id]
            if not parents:
                rank_by_stop_id[stop.id] = 1
            elif parents.issubset(rank_by_stop_id):
                rank_by_stop_id[stop.id] = (
                    max(rank_by_stop_id[parent_id] for parent_id in parents) + 1
                )
            else:
                continue
            remaining.remove(stop.id)
            progressed = True
        if not progressed:
            for stop in stops:
                if stop.id in remaining:
                    rank_by_stop_id[stop.id] = stop.position
            break
    return rank_by_stop_id


def datetime_sort_key(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def find_place(
    known_places: list[tuple[orm.Place, float, float]], latitude: float, longitude: float
) -> orm.Place | None:
    for place, place_lat, place_lon in known_places:
        if haversine_meters(place_lat, place_lon, latitude, longitude) <= STOP_RADIUS_METERS:
            return place
    return None


def add_unknown_time_reviews(
    db: Session,
    run: orm.ReconstructionRun,
    trip_id: UUID,
    points: list[MediaPoint],
) -> int:
    for point in points:
        add_review_item(
            db,
            run,
            trip_id,
            point.id,
            ReviewItemType.UNKNOWN_TIME,
            "Capture time is missing or unusable.",
            severity=ReviewSeverity.HIGH,
            payload={"reason": "missing_capture_time"},
        )
    return len(points)


def add_review_item(
    db: Session,
    run: orm.ReconstructionRun,
    trip_id: UUID,
    media_item_id: UUID,
    item_type: ReviewItemType,
    message: str,
    *,
    severity: ReviewSeverity,
    payload: dict[str, object],
) -> None:
    db.add(
        orm.ReviewItem(
            trip_id=trip_id,
            media_item_id=media_item_id,
            item_type=item_type.value,
            severity=severity.value,
            target_type="media_item",
            target_id=media_item_id,
            target_refs={"mediaItemId": str(media_item_id)},
            status=ReviewItemStatus.OPEN.value,
            message=message,
            payload=payload,
            **generated(run, 0.4),
        )
    )


def generated(run: orm.ReconstructionRun, confidence: float) -> dict[str, object]:
    return {
        "source": ReconstructionSource.AUTOMATION.value,
        "confidence": confidence,
        "algorithm_version": ALGORITHM_VERSION,
        "reconstruction_run_id": run.id,
        "user_locked": False,
    }


def point_wkt(latitude: float, longitude: float) -> str:
    return f"SRID=4326;POINT({longitude} {latitude})"


def line_wkt(from_point: object | None, to_point: object | None) -> str | None:
    if not isinstance(from_point, str) or not isinstance(to_point, str):
        return None
    from_coords = from_point.removeprefix("SRID=4326;POINT(").removesuffix(")")
    to_coords = to_point.removeprefix("SRID=4326;POINT(").removesuffix(")")
    return f"SRID=4326;LINESTRING({from_coords}, {to_coords})"


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_000
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    return 2 * earth_radius_m * asin(sqrt(a))


def implied_speed_kmh(
    lat1: float | None,
    lon1: float | None,
    lat2: float | None,
    lon2: float | None,
    minutes: float,
) -> float:
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None or minutes <= 0:
        return 0
    return (haversine_meters(lat1, lon1, lat2, lon2) / 1000) / (minutes / 60)
