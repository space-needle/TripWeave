import { describe, expect, it } from "vitest";
import type { PublicStoryResponse } from "../app/api-types";
import {
  buildFrameStory,
  frameStoryApiBaseUrl,
  publicStoryEndpoint,
} from "../app/frame-story";

const publicStory: PublicStoryResponse = {
  version: {
    id: "version-1",
    tripId: "trip-1",
    versionNumber: 1,
    state: "published",
    title: "Frame title fallback",
    publishedAt: "2026-06-02T00:00:00Z",
  },
  trip: {
    title: "Seoul weekend",
    description: "A small shared trip",
    timezoneId: "Asia/Seoul",
  },
  participants: [],
  story: {
    latestRun: {
      id: "run-1",
      state: "succeeded",
      algorithmVersion: "reconstruction_v1",
      summary: {},
      startedAt: "2026-06-01T00:00:00Z",
      finishedAt: "2026-06-01T00:01:00Z",
    },
    reviewItems: [],
    storyUpdate: {
      needsUpdate: false,
      unassignedReadyMediaCount: 0,
      readyMediaCount: 2,
      storyMediaCount: 2,
    },
    days: [
      {
        id: "day-1",
        date: "2026-06-01",
        position: 1,
        title: "Arrival",
        stops: [
          {
            id: "stop-1",
            position: 1,
            title: "Cafe stop",
            startsAt: "2026-06-01T01:00:00Z",
            endsAt: "2026-06-01T02:00:00Z",
            latitude: 37.56,
            longitude: 126.97,
            mediaCount: 1,
            contributorCount: 1,
            moments: [
              {
                id: "moment-1",
                position: 1,
                startsAt: "2026-06-01T01:00:00Z",
                endsAt: "2026-06-01T02:00:00Z",
                mediaCount: 1,
                contributorCount: 1,
                media: [
                  {
                    id: "media-1",
                    filename: "arrival.jpg",
                    capturedAt: "2026-06-01T01:00:00Z",
                    contributorMemberId: "member-1",
                    contributor: "Owner",
                    previewUrl: "/public/shares/token/assets/preview",
                  },
                ],
              },
            ],
          },
          {
            id: "stop-2",
            position: 2,
            placeName: "Namsan",
            startsAt: "2026-06-01T03:00:00Z",
            endsAt: "2026-06-01T04:00:00Z",
            latitude: 37.55,
            longitude: 126.99,
            mediaCount: 1,
            contributorCount: 1,
            moments: [
              {
                id: "moment-2",
                position: 1,
                startsAt: "2026-06-01T03:00:00Z",
                endsAt: "2026-06-01T04:00:00Z",
                mediaCount: 1,
                contributorCount: 1,
                media: [
                  {
                    id: "media-2",
                    filename: "tower.jpg",
                    capturedAt: "2026-06-01T03:00:00Z",
                    contributorMemberId: "member-1",
                    contributor: "Owner",
                    thumbnailUrl: "/public/shares/token/assets/thumb",
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
                [126.99, 37.55],
              ],
            },
          },
        ],
      },
    ],
  },
};

describe("frame story", () => {
  it("builds legacy frame scenes from the published story only", () => {
    const frame = buildFrameStory(publicStory);

    expect(frame.title).toBe("Seoul weekend");
    expect(frame.subtitle).toBe("A small shared trip");
    expect(frame.scenes.map((scene) => scene.type)).toEqual([
      "map",
      "map",
      "map",
      "photo",
      "map",
      "photo",
    ]);
    expect(frame.scenes[0]).toMatchObject({
      title: "Trip overview",
      routes: [],
    });
    expect(frame.scenes[1]).toMatchObject({
      title: "Arrival",
      routes: [{ id: "leg-1", points: "10,15 90,85" }],
    });
    expect(frame.scenes[3]).toMatchObject({
      type: "photo",
      imageUrl: "/public/shares/token/assets/preview",
    });
  });

  it("prefers the internal API URL for server-side story fetches", () => {
    expect(
      frameStoryApiBaseUrl("http://api:8000/", "https://tripweave.example/api"),
    ).toBe("http://api:8000");
    expect(publicStoryEndpoint("http://api:8000", "seoul-weekend-a7f3c9")).toBe(
      "http://api:8000/public/stories/seoul-weekend-a7f3c9",
    );
    expect(publicStoryEndpoint("http://api:8000", "seoul-weekend-a7f3c9", 2)).toBe(
      "http://api:8000/public/stories/seoul-weekend-a7f3c9/versions/2",
    );
  });
});
