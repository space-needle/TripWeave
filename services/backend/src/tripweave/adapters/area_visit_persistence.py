from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import ColumnElement, delete, literal_column, or_, select
from sqlalchemy.orm import Session

from tripweave.adapters import orm
from tripweave.application.area_visits import (
    AreaDecisionDiagnostic,
    AreaGroupingResult,
    AreaVisitConfig,
    AreaVisitResult,
    StopInput,
    group_area_visits,
)
from tripweave.domain.enums import (
    ReconstructionSource,
    ReviewItemStatus,
    ReviewItemType,
    ReviewSeverity,
)

LOW_CONFIDENCE_REVIEW_THRESHOLD = 0.70


def persist_area_visits_for_trip(
    *,
    db: Session,
    trip_id: UUID,
    run: orm.ReconstructionRun,
) -> list[dict[str, object]]:
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
                orm.TripDay.starts_at_utc,
                orm.TripDay.position,
                orm.TripDay.id,
            )
        )
    )
    summaries: list[dict[str, object]] = []
    for day in days:
        stop_rows = load_stops(db, trip_id, day.id)
        result = group_area_visits(stop_inputs_from_rows(stop_rows), AreaVisitConfig())
        summaries.append(
            persist_grouping_result(
                db=db,
                trip_id=trip_id,
                day_id=day.id,
                run=run,
                result=result,
                stop_rows=stop_rows,
            )
        )
    return summaries


def persist_grouping_result(
    *,
    db: Session,
    trip_id: UUID,
    day_id: UUID,
    run: orm.ReconstructionRun,
    result: AreaGroupingResult,
    stop_rows: list[tuple[orm.Stop, float | None, float | None]],
) -> dict[str, object]:
    stops_by_id = {str(stop.id): stop for stop, _, _ in stop_rows}
    stop_ids = [stop.id for stop, _, _ in stop_rows]
    result_summary = cast(dict[str, object], result.to_dict()["summary"])
    if locked_area_visit_data_exists(db, trip_id, day_id, run.id, stop_ids):
        return {
            "trip_id": str(trip_id),
            "day_id": str(day_id),
            "reconstruction_run_id": str(run.id),
            "persisted_area_visit_ids": [],
            "skipped": True,
            "skip_reason": "locked_area_visit_data_exists",
            **result_summary,
        }

    delete_existing_generated_area_visits(db, trip_id, day_id, run.id, stop_ids)
    persisted_area_ids: list[str] = []
    review_count = 0
    for sort_order, area in enumerate(result.areas, start=1):
        persisted_area = orm.AreaVisit(
            trip_id=trip_id,
            trip_day_id=day_id,
            title=None,
            sort_order=sort_order,
            starts_at_utc=area.start_time,
            ends_at_utc=area.end_time,
            center=point_wkt(area.center_latitude, area.center_longitude),
            bounds=area.bounds,
            diagnostics=diagnostics_for_area(area, result.diagnostics),
            source=ReconstructionSource.AUTOMATION.value,
            confidence=area.confidence,
            algorithm_version=area.algorithm_version,
            reconstruction_run_id=run.id,
            user_locked=False,
        )
        db.add(persisted_area)
        db.flush()
        persisted_area_ids.append(str(persisted_area.id))
        for membership_order, stop_id in enumerate(area.stop_ids, start=1):
            stop = stops_by_id[stop_id]
            db.add(
                orm.AreaVisitStop(
                    trip_id=trip_id,
                    area_visit_id=persisted_area.id,
                    stop_id=stop.id,
                    reconstruction_run_id=run.id,
                    sort_order=membership_order,
                    membership_source=ReconstructionSource.AUTOMATION.value,
                    confidence=area.confidence,
                    algorithm_version=area.algorithm_version,
                    user_locked=False,
                )
            )
        if add_low_confidence_area_review(
            db=db,
            trip_id=trip_id,
            day_id=day_id,
            run=run,
            area=area,
            persisted_area=persisted_area,
        ):
            review_count += 1
    return {
        "trip_id": str(trip_id),
        "day_id": str(day_id),
        "reconstruction_run_id": str(run.id),
        "persisted_area_visit_ids": persisted_area_ids,
        "area_review_count": review_count,
        **result_summary,
    }


def locked_area_visit_data_exists(
    db: Session,
    trip_id: UUID,
    day_id: UUID,
    reconstruction_run_id: UUID,
    stop_ids: list[UUID],
) -> bool:
    locked_area_id = db.scalar(
        select(orm.AreaVisit.id)
        .where(
            orm.AreaVisit.trip_id == trip_id,
            orm.AreaVisit.trip_day_id == day_id,
            orm.AreaVisit.user_locked.is_(True),
        )
        .limit(1)
    )
    if locked_area_id is not None:
        return True
    if not stop_ids:
        return False
    locked_membership_id = db.scalar(
        select(orm.AreaVisitStop.id)
        .where(
            orm.AreaVisitStop.trip_id == trip_id,
            orm.AreaVisitStop.reconstruction_run_id == reconstruction_run_id,
            orm.AreaVisitStop.stop_id.in_(stop_ids),
            orm.AreaVisitStop.user_locked.is_(True),
        )
        .limit(1)
    )
    return locked_membership_id is not None


def add_low_confidence_area_review(
    *,
    db: Session,
    trip_id: UUID,
    day_id: UUID,
    run: orm.ReconstructionRun,
    area: AreaVisitResult,
    persisted_area: orm.AreaVisit,
) -> bool:
    if area.confidence >= LOW_CONFIDENCE_REVIEW_THRESHOLD:
        return False
    existing = db.scalar(
        select(orm.ReviewItem.id)
        .where(
            orm.ReviewItem.trip_id == trip_id,
            orm.ReviewItem.target_type == "area_visit",
            orm.ReviewItem.target_id == persisted_area.id,
        )
        .limit(1)
    )
    if existing is not None:
        return False
    db.add(
        orm.ReviewItem(
            trip_id=trip_id,
            media_item_id=None,
            item_type=ReviewItemType.POSSIBLE_AREA_VISIT.value,
            severity=ReviewSeverity.LOW.value,
            target_type="area_visit",
            target_id=persisted_area.id,
            target_refs={
                "areaVisitId": str(persisted_area.id),
                "dayId": str(day_id),
                "stopIds": area.stop_ids,
            },
            status=ReviewItemStatus.OPEN.value,
            message=(
                "AreaVisit grouping has low confidence. Review the included stops "
                "before publishing."
            ),
            payload={
                "areaVisitId": str(persisted_area.id),
                "dayId": str(day_id),
                "stopIds": area.stop_ids,
                "stopCount": len(area.stop_ids),
                "confidence": area.confidence,
                "threshold": LOW_CONFIDENCE_REVIEW_THRESHOLD,
                "diameterMeters": area.diameter_m,
                "algorithmVersion": area.algorithm_version,
            },
            source=ReconstructionSource.AUTOMATION.value,
            confidence=area.confidence,
            algorithm_version=area.algorithm_version,
            reconstruction_run_id=run.id,
            user_locked=False,
        )
    )
    return True


def delete_existing_generated_area_visits(
    db: Session,
    trip_id: UUID,
    day_id: UUID,
    reconstruction_run_id: UUID,
    stop_ids: list[UUID],
) -> None:
    db.execute(
        delete(orm.AreaVisitStop).where(
            orm.AreaVisitStop.trip_id == trip_id,
            orm.AreaVisitStop.reconstruction_run_id == reconstruction_run_id,
            orm.AreaVisitStop.stop_id.in_(stop_ids),
            orm.AreaVisitStop.user_locked.is_(False),
        )
    )
    db.execute(
        delete(orm.AreaVisit).where(
            orm.AreaVisit.trip_id == trip_id,
            orm.AreaVisit.trip_day_id == day_id,
            orm.AreaVisit.reconstruction_run_id == reconstruction_run_id,
            orm.AreaVisit.user_locked.is_(False),
        )
    )


def diagnostics_for_area(
    area: AreaVisitResult,
    diagnostics: list[AreaDecisionDiagnostic],
) -> dict[str, object]:
    area_stop_ids = set(area.stop_ids)
    return {
        "decisions": [
            diagnostic.to_dict()
            for diagnostic in diagnostics
            if diagnostic.candidate_stop_id in area_stop_ids
        ]
    }


def point_wkt(latitude: float, longitude: float) -> str:
    return f"SRID=4326;POINT({longitude} {latitude})"


def load_stop_inputs(
    db: Session,
    trip_id: UUID,
    day_id: UUID,
) -> list[StopInput]:
    rows = load_stops(db, trip_id, day_id)
    return stop_inputs_from_rows(rows)


def stop_inputs_from_rows(
    rows: list[tuple[orm.Stop, float | None, float | None]],
) -> list[StopInput]:
    return [
        StopInput(
            id=str(stop.id),
            day_id=str(stop.trip_day_id),
            sort_order=stop.position,
            start_time=stop.starts_at_utc,
            end_time=stop.ends_at_utc,
            latitude=float(latitude) if latitude is not None else None,
            longitude=float(longitude) if longitude is not None else None,
            location_confidence=stop.confidence,
        )
        for stop, latitude, longitude in rows
    ]


def load_stops(
    db: Session,
    trip_id: UUID,
    day_id: UUID,
) -> list[tuple[orm.Stop, float | None, float | None]]:
    stop_lat: ColumnElement[float | None] = literal_column("ST_Y(stops.centroid::geometry)").label(
        "latitude"
    )
    stop_lon: ColumnElement[float | None] = literal_column("ST_X(stops.centroid::geometry)").label(
        "longitude"
    )
    rows = db.execute(
        select(orm.Stop, stop_lat, stop_lon)
        .where(
            orm.Stop.trip_id == trip_id,
            orm.Stop.trip_day_id == day_id,
        )
        .order_by(orm.Stop.position, orm.Stop.starts_at_utc, orm.Stop.id)
    ).all()
    return [(stop, latitude, longitude) for stop, latitude, longitude in rows]
