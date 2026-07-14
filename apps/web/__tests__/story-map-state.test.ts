import { describe, expect, it } from "vitest";
import type { ReconstructionResponse } from "../app/api-types";
import {
  EVERYONE,
  advancePlayback,
  buildStoryModel,
  filterStoryModel,
  followStory,
  initialStoryMapState,
  markUserControlled,
  normalizeStoryMapState,
  selectStoryStop,
  setContributorFilter,
} from "../app/story-map-state";

const reconstruction: ReconstructionResponse = {
  latestRun: {
    id: "run",
    state: "succeeded",
    algorithmVersion: "reconstruction_v1",
    summary: {},
    startedAt: "2026-06-01T00:00:00Z",
    finishedAt: "2026-06-01T00:01:00Z",
  },
  reviewItems: [],
  days: [
    {
      id: "day-1",
      date: "2026-06-01",
      position: 1,
      stops: [
        {
          id: "stop-1",
          position: 1,
          startsAt: "2026-06-01T01:00:00Z",
          endsAt: "2026-06-01T02:00:00Z",
          latitude: 37.56,
          longitude: 126.97,
          mediaCount: 2,
          contributorCount: 2,
          moments: [
            {
              id: "moment-1",
              position: 1,
              startsAt: "2026-06-01T01:00:00Z",
              endsAt: "2026-06-01T01:20:00Z",
              mediaCount: 2,
              contributorCount: 2,
              media: [
                {
                  id: "media-1",
                  capturedAt: "2026-06-01T01:00:00Z",
                  latitude: 37.56,
                  longitude: 126.97,
                  contributorMemberId: "member-1",
                  contributor: "Owner",
                },
                {
                  id: "media-2",
                  capturedAt: "2026-06-01T01:10:00Z",
                  latitude: 37.56001,
                  longitude: 126.97001,
                  contributorMemberId: "member-2",
                  contributor: "Guest",
                },
              ],
            },
          ],
        },
      ],
      legs: [
        {
          id: "leg-1",
          fromStopId: "stop-1",
          toStopId: "stop-2",
          routeSource: "photo_inferred",
          geometry: {
            type: "LineString",
            coordinates: [
              [126.97, 37.56],
              [126.98, 37.57],
            ],
          },
        },
      ],
    },
  ],
};

describe("story map state", () => {
  it("builds a provider-neutral story model from reconstruction output", () => {
    const model = buildStoryModel(reconstruction);

    expect(model.stops).toHaveLength(1);
    expect(model.media).toHaveLength(2);
    expect(model.legs[0]).toMatchObject({ routeSource: "photo_inferred" });
    expect(model.stacks[0].mediaIds).toEqual(["media-1", "media-2"]);
  });

  it("filters contributor perspectives without losing contributor choices", () => {
    const model = buildStoryModel(reconstruction);
    const filtered = filterStoryModel(model, "member-2");

    expect(model.contributors.map((item) => item.id)).toEqual([
      "member-2",
      "member-1",
    ]);
    expect(filtered.media.map((item) => item.id)).toEqual(["media-2"]);
    expect(filterStoryModel(model, EVERYONE).media).toHaveLength(2);
  });

  it("tracks map control and restores story following", () => {
    const selected = selectStoryStop(initialStoryMapState(), "stop-1", "day-1");
    const userControlled = markUserControlled(selected);
    const following = followStory(userControlled);

    expect(selected).toMatchObject({
      viewMode: "STOP",
      selectedDayId: "day-1",
      selectedStopId: "stop-1",
      mapControlMode: "STORY_CONTROLLED",
    });
    expect(userControlled.mapControlMode).toBe("USER_CONTROLLED");
    expect(following.mapControlMode).toBe("STORY_CONTROLLED");
  });

  it("normalizes empty or stale selection after reconstruction loads", () => {
    const model = buildStoryModel(reconstruction);
    const normalized = normalizeStoryMapState(initialStoryMapState(), model);
    const stale = normalizeStoryMapState(
      {
        ...normalized,
        selectedDayId: "missing-day",
        selectedStopId: "missing-stop",
        selectedMomentId: "missing-moment",
        selectedMediaId: "missing-media",
      },
      model,
    );

    expect(normalized).toMatchObject({
      viewMode: "DAY",
      selectedDayId: "day-1",
      selectedStopId: "stop-1",
      selectedMomentId: "moment-1",
      selectedMediaId: "media-1",
      mapControlMode: "STORY_CONTROLLED",
    });
    expect(stale.selectedStopId).toBe("stop-1");
  });

  it("advances playback through chronological media", () => {
    const model = buildStoryModel(reconstruction);
    const state = setContributorFilter(initialStoryMapState(), EVERYONE);
    const next = advancePlayback(state, model);
    const afterNext = advancePlayback(next, model);

    expect(next).toMatchObject({
      viewMode: "PLAYBACK",
      selectedMediaId: "media-1",
      timeCursor: "2026-06-01T01:00:00Z",
    });
    expect(afterNext.selectedMediaId).toBe("media-2");
  });
});
