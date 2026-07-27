from __future__ import annotations

import argparse
import json
from typing import cast
from uuid import UUID

from sqlalchemy import ColumnElement, delete, literal_column, select
from sqlalchemy.orm import Session

from tripweave.adapters import orm
from tripweave.adapters.database import create_database_engine
from tripweave.adapters.reconstruction import latest_reconstruction_run
from tripweave.application.area_visits import (
    AreaDecisionDiagnostic,
    AreaGroupingResult,
    AreaVisitConfig,
    AreaVisitResult,
    StopInput,
    group_area_visits,
)
from tripweave.config import Settings
from tripweave.domain.enums import ReconstructionSource


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "preview":
        preview_area_visits(args)
    elif args.command == "persist":
        persist_area_visits(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tripweave-area-visits")
    subparsers = parser.add_subparsers(dest="command", required=True)
    preview = subparsers.add_parser("preview", help="Preview AreaVisit grouping without writes.")
    preview.add_argument("--trip-id", required=True, type=UUID)
    preview.add_argument("--day-id", required=True, type=UUID)
    persist = subparsers.add_parser("persist", help="Persist AreaVisit grouping for a trip day.")
    persist.add_argument("--trip-id", required=True, type=UUID)
    persist.add_argument("--day-id", required=True, type=UUID)
    return parser


def preview_area_visits(args: argparse.Namespace) -> None:
    settings = Settings()
    engine = create_database_engine(settings)
    with Session(engine) as db:
        trip = db.get(orm.Trip, args.trip_id)
        if trip is None:
            raise SystemExit(f"Trip not found: {args.trip_id}")
        run = latest_reconstruction_run(db, trip.id)
        if run is None:
            raise SystemExit(f"No successful reconstruction run found for trip: {args.trip_id}")
        trip_day = db.get(orm.TripDay, args.day_id)
        if trip_day is None or trip_day.trip_id != trip.id:
            raise SystemExit(f"Trip day not found for trip: {args.day_id}")
        stop_rows = load_stops(db, trip.id, trip_day.id)
        stops = stop_inputs_from_rows(stop_rows)
        result = group_area_visits(stops, AreaVisitConfig())
        payload = {
            "trip_id": str(trip.id),
            "day_id": str(trip_day.id),
            "day_date": trip_day.day_date.isoformat(),
            "latest_reconstruction_run_id": str(run.id),
            "source_reconstruction_run_ids": sorted(
                {str(stop.reconstruction_run_id) for stop, _, _ in stop_rows}
            ),
            **result.to_dict(),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))


def persist_area_visits(args: argparse.Namespace) -> None:
    settings = Settings()
    engine = create_database_engine(settings)
    with Session(engine) as db:
        trip = db.get(orm.Trip, args.trip_id)
        if trip is None:
            raise SystemExit(f"Trip not found: {args.trip_id}")
        run = latest_reconstruction_run(db, trip.id)
        if run is None:
            raise SystemExit(f"No successful reconstruction run found for trip: {args.trip_id}")
        trip_day = db.get(orm.TripDay, args.day_id)
        if trip_day is None or trip_day.trip_id != trip.id:
            raise SystemExit(f"Trip day not found for trip: {args.day_id}")
        stop_rows = load_stops(db, trip.id, trip_day.id)
        result = group_area_visits(stop_inputs_from_rows(stop_rows), AreaVisitConfig())
        summary = persist_grouping_result(
            db=db,
            trip_id=trip.id,
            day_id=trip_day.id,
            run=run,
            result=result,
            stop_rows=stop_rows,
        )
        db.commit()
        print(json.dumps(summary, indent=2, sort_keys=True))


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
    delete_existing_generated_area_visits(db, trip_id, day_id, run.id, stop_ids)
    persisted_area_ids: list[str] = []
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
    result_summary = cast(dict[str, object], result.to_dict()["summary"])
    return {
        "trip_id": str(trip_id),
        "day_id": str(day_id),
        "reconstruction_run_id": str(run.id),
        "persisted_area_visit_ids": persisted_area_ids,
        **result_summary,
    }


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


if __name__ == "__main__":
    main()
