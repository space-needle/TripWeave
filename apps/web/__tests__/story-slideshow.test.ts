import { describe, expect, it } from "vitest";
import type { PublicStoryResponse } from "../app/api-types";
import {
  buildPublicStorySlideshowPhotos,
  buildPublicStorySlideshowScenes,
} from "../app/story-slideshow";

const publicStory: PublicStoryResponse = {
  version: {
    id: "version-1",
    tripId: "trip-1",
    versionNumber: 1,
    state: "published",
    title: "Seoul weekend",
    publishedAt: "2026-06-02T00:00:00Z",
  },
  trip: {
    title: "Seoul weekend",
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
      readyMediaCount: 3,
      storyMediaCount: 3,
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
            mediaCount: 2,
            contributorCount: 1,
            moments: [
              {
                id: "moment-1",
                position: 1,
                startsAt: "2026-06-01T01:00:00Z",
                endsAt: "2026-06-01T02:00:00Z",
                mediaCount: 2,
                contributorCount: 1,
                media: [
                  {
                    id: "media-1",
                    filename: "arrival.jpg",
                    capturedAt: "2026-06-01T01:00:00Z",
                    contributorMemberId: "member-1",
                    contributor: "Owner",
                    thumbnailUrl: "/thumbs/arrival.jpg",
                    previewUrl: "/previews/arrival.jpg",
                  },
                  {
                    id: "media-2",
                    filename: "private-original-only.jpg",
                    capturedAt: "2026-06-01T01:30:00Z",
                    contributorMemberId: "member-1",
                    contributor: "Owner",
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
                    id: "media-3",
                    filename: "tower.jpg",
                    capturedAt: "2026-06-01T03:00:00Z",
                    capturedAtLocal: "2026-06-01T12:00:00",
                    contributorMemberId: "member-1",
                    contributor: "Owner",
                    thumbnailUrl: "/thumbs/tower.jpg",
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

describe("story slideshow", () => {
  it("starts with a trip overview before day, stop, and photo scenes", () => {
    const scenes = buildPublicStorySlideshowScenes(publicStory);

    expect(scenes.map((scene) => scene.id)).toEqual([
      "trip:overview",
      "day:day-1",
      "stop:stop-1",
      "photo:media-1",
      "stop:stop-2",
      "photo:media-3",
    ]);
    expect(scenes[0]).toMatchObject({
      type: "trip",
      title: "Trip overview",
      durationMs: 3000,
      photoCount: 2,
      dayMarkers: [
        {
          id: "day-1",
          label: "Arrival",
          imageUrl: "/previews/arrival.jpg",
        },
      ],
    });
    expect(scenes[0].type === "trip" ? scenes[0].routes : []).toEqual([]);
    expect(scenes[1]).toMatchObject({
      type: "day",
      title: "Arrival",
      durationMs: 3000,
      photoCount: 2,
    });
    expect(
      scenes[1].type === "day" ? scenes[1].routes[0].coordinates : [],
    ).toEqual([
      [126.97, 37.56],
      [126.99, 37.55],
    ]);
    expect(scenes[2]).toMatchObject({
      type: "stop",
      title: "Cafe stop",
      activeStopId: "stop-1",
      durationMs: 3000,
      photoCount: 1,
    });
    expect(scenes[3]).toMatchObject({ type: "photo", durationMs: 5000 });
  });

  it("uses published derivatives and preserves story order", () => {
    const photos = buildPublicStorySlideshowPhotos(publicStory);

    expect(photos).toEqual([
      {
        id: "media-1",
        imageUrl: "/previews/arrival.jpg",
        thumbnailUrl: "/thumbs/arrival.jpg",
        filename: "arrival.jpg",
        contributor: "Owner",
        capturedAt: "2026-06-01T01:00:00Z",
        capturedAtLocal: null,
        dayLabel: "Arrival",
        stopLabel: "Cafe stop",
      },
      {
        id: "media-3",
        imageUrl: "/thumbs/tower.jpg",
        thumbnailUrl: "/thumbs/tower.jpg",
        filename: "tower.jpg",
        contributor: "Owner",
        capturedAt: "2026-06-01T03:00:00Z",
        capturedAtLocal: "2026-06-01T12:00:00",
        dayLabel: "Arrival",
        stopLabel: "Namsan",
      },
    ]);
  });

  it("uses the calendar date when a day has no title", () => {
    const untitledStory: PublicStoryResponse = {
      ...publicStory,
      story: {
        ...publicStory.story,
        days: publicStory.story.days.map((day) => ({
          ...day,
          title: null,
        })),
      },
    };

    const scenes = buildPublicStorySlideshowScenes(untitledStory);

    expect(scenes[1]).toMatchObject({ type: "day", title: "6/1" });
    expect(scenes[2]).toMatchObject({ type: "stop", dayLabel: "6/1" });
  });
});
