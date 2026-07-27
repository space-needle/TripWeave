from __future__ import annotations

import argparse
import json
from uuid import UUID

from sqlalchemy import ColumnElement, literal_column, select
from sqlalchemy.orm import Session

from tripweave.adapters import orm
from tripweave.adapters.database import create_database_engine
from tripweave.adapters.reconstruction import latest_reconstruction_run
from tripweave.application.area_visits import AreaVisitConfig, StopInput, group_area_visits
from tripweave.config import Settings


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "preview":
        preview_area_visits(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tripweave-area-visits")
    subparsers = parser.add_subparsers(dest="command", required=True)
    preview = subparsers.add_parser("preview", help="Preview AreaVisit grouping without writes.")
    preview.add_argument("--trip-id", required=True, type=UUID)
    preview.add_argument("--day-id", required=True, type=UUID)
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
        stops = load_stop_inputs(db, trip.id, trip_day.id, run.id)
        result = group_area_visits(stops, AreaVisitConfig())
        payload = {
            "trip_id": str(trip.id),
            "day_id": str(trip_day.id),
            "day_date": trip_day.day_date.isoformat(),
            "reconstruction_run_id": str(run.id),
            **result.to_dict(),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))


def load_stop_inputs(
    db: Session,
    trip_id: UUID,
    day_id: UUID,
    reconstruction_run_id: UUID,
) -> list[StopInput]:
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
            orm.Stop.reconstruction_run_id == reconstruction_run_id,
        )
        .order_by(orm.Stop.position, orm.Stop.starts_at_utc, orm.Stop.id)
    ).all()
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


if __name__ == "__main__":
    main()
