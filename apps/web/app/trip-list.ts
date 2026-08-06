import type { TripResponse } from "./api-types";

export type TripYearGroup = {
  year: string;
  trips: TripResponse[];
};

export function groupTripsByYear(trips: TripResponse[]): TripYearGroup[] {
  const groups = new Map<string, TripResponse[]>();

  for (const trip of trips) {
    const year = tripYear(trip);
    const group = groups.get(year) ?? [];
    group.push(trip);
    groups.set(year, group);
  }

  return Array.from(groups, ([year, groupedTrips]) => ({
    year,
    trips: [...groupedTrips].sort((left, right) =>
      tripDate(left).localeCompare(tripDate(right)),
    ),
  })).sort((left, right) => {
    if (left.year === "Unscheduled") {
      return 1;
    }
    if (right.year === "Unscheduled") {
      return -1;
    }
    return Number(left.year) - Number(right.year);
  });
}

function tripYear(trip: TripResponse): string {
  const date = trip.startDate ?? trip.endDate;
  const match = date?.match(/^(\d{4})-/);
  return match?.[1] ?? "Unscheduled";
}

function tripDate(trip: TripResponse): string {
  return trip.startDate ?? trip.endDate ?? "9999-12-31";
}
