from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import ColumnElement, delete, literal_column, select
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
    delete_unlocked_outputs(db, trip.id)

    media_points = load_media_points(db, trip)
    usable: list[MediaPoint] = []
    review_count = 0
    for point in media_points:
        if point.captured_at_utc is None:
            add_review_item(
                db,
                run,
                trip.id,
                point.id,
                ReviewItemType.UNKNOWN_TIME,
                "Capture time is missing or unusable.",
                severity=ReviewSeverity.HIGH,
                payload={"reason": "missing_capture_time"},
            )
            review_count += 1
            continue
        point.day = effective_day(trip, point)
        usable.append(point)

    gps_points = [
        point for point in usable if point.latitude is not None and point.longitude is not None
    ]
    clusters = cluster_stops(gps_points)
    created = persist_clusters(db, run, trip.id, clusters, geocoder)
    review_count += assign_missing_gps(db, run, trip.id, usable, gps_points)
    moments = persist_moments(db, run, created, usable)
    legs = persist_legs(db, run, created)
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


def delete_unlocked_outputs(db: Session, trip_id: UUID) -> None:
    for model in (
        orm.ReviewItem,
        orm.TripLeg,
        orm.MomentParticipant,
        orm.MomentMedia,
        orm.Moment,
        orm.Stop,
        orm.Place,
        orm.TripDay,
    ):
        db.execute(delete(model).where(model.trip_id == trip_id, model.user_locked.is_(False)))


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
    for day_position, day in enumerate(sorted(clusters_by_day), start=1):
        clusters = clusters_by_day[day]
        trip_day = orm.TripDay(
            trip_id=trip_id,
            day_date=day,
            position=day_position,
            starts_at_utc=min(cluster.start for cluster in clusters) if clusters else None,
            ends_at_utc=max(cluster.end for cluster in clusters) if clusters else None,
            **generated(run, 0.95),
        )
        db.add(trip_day)
        db.flush()
        stops: list[orm.Stop] = []
        for stop_position, cluster in enumerate(clusters, start=1):
            place = find_place(known_places, cluster.latitude, cluster.longitude)
            if place is None:
                name = geocoder.name_for_point(
                    latitude=cluster.latitude, longitude=cluster.longitude
                ).name
                place = orm.Place(
                    trip_id=trip_id,
                    name=name,
                    centroid=point_wkt(cluster.latitude, cluster.longitude),
                    **generated(run, 0.9),
                )
                db.add(place)
                db.flush()
                known_places.append((place, cluster.latitude, cluster.longitude))
            stop = orm.Stop(
                trip_id=trip_id,
                trip_day_id=trip_day.id,
                place_id=place.id,
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
    db: Session, run: orm.ReconstructionRun, created: dict[orm.TripDay, list[orm.Stop]]
) -> int:
    count = 0
    for trip_day, stops in created.items():
        ordered = sorted(stops, key=lambda stop: stop.position)
        for previous, current in zip(ordered, ordered[1:], strict=False):
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


def find_place(
    known_places: list[tuple[orm.Place, float, float]], latitude: float, longitude: float
) -> orm.Place | None:
    for place, place_lat, place_lon in known_places:
        if haversine_meters(place_lat, place_lon, latitude, longitude) <= STOP_RADIUS_METERS:
            return place
    return None


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
