import { describe, expect, it } from "vitest";
import type { TripResponse } from "../app/api-types";
import { groupTripsByYear } from "../app/trip-list";

function trip(
  id: string,
  startDate: string | null,
  endDate: string | null = null,
): TripResponse {
  return {
    id,
    title: id,
    description: null,
    startDate,
    endDate,
    timezoneId: "Asia/Seoul",
    dayCutoffHour: 4,
    status: "active",
    visibility: "private",
    role: "owner",
    memberId: `member-${id}`,
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
  };
}

describe("groupTripsByYear", () => {
  it("groups trips by travel year in chronological order", () => {
    const groups = groupTripsByYear([
      trip("china", "2022-10-02"),
      trip("korea-2015", "2015-05-03"),
      trip("washington", "2023-03-08"),
      trip("korea-2022", "2022-04-10"),
    ]);

    expect(groups.map((group) => group.year)).toEqual(["2015", "2022", "2023"]);
    expect(groups[1].trips.map((item) => item.id)).toEqual([
      "korea-2022",
      "china",
    ]);
  });

  it("uses the end date when a trip has no start date and keeps undated trips separate", () => {
    const groups = groupTripsByYear([
      trip("undated", null),
      trip("weekend", null, "2024-02-04"),
    ]);

    expect(groups.map((group) => group.year)).toEqual(["2024", "Unscheduled"]);
    expect(groups[0].trips.map((item) => item.id)).toEqual(["weekend"]);
  });
});
