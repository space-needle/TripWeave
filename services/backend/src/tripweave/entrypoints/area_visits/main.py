from __future__ import annotations

import argparse
import json
from uuid import UUID

from sqlalchemy.orm import Session

from tripweave.adapters import orm
from tripweave.adapters.area_visit_persistence import (
    load_stops,
    persist_grouping_result,
    stop_inputs_from_rows,
)
from tripweave.adapters.database import create_database_engine
from tripweave.adapters.reconstruction import latest_reconstruction_run
from tripweave.application.area_visits import AreaVisitConfig, group_area_visits
from tripweave.config import Settings


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


if __name__ == "__main__":
    main()
