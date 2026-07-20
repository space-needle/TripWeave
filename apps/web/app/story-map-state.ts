import type { ReconstructionResponse } from "./api-types";

export type GeoJsonLineString = {
  type: "LineString";
  coordinates: number[][];
};

export type ViewMode = "TRIP_OVERVIEW" | "DAY" | "STOP" | "MOMENT" | "PLAYBACK";

export type MapControlMode = "STORY_CONTROLLED" | "USER_CONTROLLED";

export type StoryMapState = {
  viewMode: ViewMode;
  selectedDayId: string | null;
  selectedStopId: string | null;
  selectedMomentId: string | null;
  selectedMediaId: string | null;
  timeCursor: string | null;
  contributorFilter: string;
  mapControlMode: MapControlMode;
};

export type StoryMediaPoint = {
  id: string;
  dayId: string;
  stopId: string;
  momentId: string;
  contributorMemberId: string;
  contributor: string;
  capturedAt: string | null;
  filename: string | null;
  thumbnailUrl: string | null;
  previewUrl: string | null;
  coordinates: [number, number] | null;
};

export type StoryStopPoint = {
  id: string;
  dayId: string;
  label: string;
  position: number;
  displayPosition: string;
  startsAt: string;
  endsAt: string;
  coordinates: [number, number] | null;
};

export type StoryLegLine = {
  id: string;
  dayId: string;
  fromStopId: string;
  toStopId: string;
  routeSource: string;
  isForked: boolean;
  geometry: GeoJsonLineString | null;
};

export type StoryPhotoStack = {
  id: string;
  coordinates: [number, number];
  mediaIds: string[];
};

export type StoryModel = {
  contributors: Array<{ id: string; name: string }>;
  stops: StoryStopPoint[];
  media: StoryMediaPoint[];
  legs: StoryLegLine[];
  stacks: StoryPhotoStack[];
};

export const EVERYONE = "everyone";

export function initialStoryMapState(): StoryMapState {
  return {
    viewMode: "TRIP_OVERVIEW",
    selectedDayId: null,
    selectedStopId: null,
    selectedMomentId: null,
    selectedMediaId: null,
    timeCursor: null,
    contributorFilter: EVERYONE,
    mapControlMode: "STORY_CONTROLLED",
  };
}

export function normalizeStoryMapState(
  state: StoryMapState,
  model: StoryModel,
): StoryMapState {
  const selectedDayStillExists = model.stops.some(
    (stop) => stop.dayId === state.selectedDayId,
  );
  const selectedStopStillExists = model.stops.some(
    (stop) => stop.id === state.selectedStopId,
  );
  const selectedMomentStillExists = model.media.some(
    (item) => item.momentId === state.selectedMomentId,
  );
  const selectedMediaStillExists = model.media.some(
    (item) => item.id === state.selectedMediaId,
  );

  if (
    selectedDayStillExists &&
    (!state.selectedStopId || selectedStopStillExists) &&
    (!state.selectedMomentId || selectedMomentStillExists) &&
    (!state.selectedMediaId || selectedMediaStillExists)
  ) {
    return state;
  }

  const firstStop = model.stops[0] ?? null;
  const firstMedia = firstStop
    ? (model.media.find((item) => item.stopId === firstStop.id) ?? null)
    : null;

  return {
    ...state,
    viewMode: firstStop ? "DAY" : "TRIP_OVERVIEW",
    selectedDayId: firstStop?.dayId ?? null,
    selectedStopId: null,
    selectedMomentId: null,
    selectedMediaId: null,
    timeCursor: firstMedia?.capturedAt ?? null,
    mapControlMode: "STORY_CONTROLLED",
  };
}

export function selectStoryDay(
  state: StoryMapState,
  dayId: string,
): StoryMapState {
  return {
    ...state,
    viewMode: "DAY",
    selectedDayId: dayId,
    selectedStopId: null,
    selectedMomentId: null,
    selectedMediaId: null,
    mapControlMode: "STORY_CONTROLLED",
  };
}

export function selectStoryStop(
  state: StoryMapState,
  stopId: string,
  dayId: string,
): StoryMapState {
  return {
    ...state,
    viewMode: "STOP",
    selectedDayId: dayId,
    selectedStopId: stopId,
    selectedMomentId: null,
    selectedMediaId: null,
    mapControlMode: "STORY_CONTROLLED",
  };
}

export function selectStoryMoment(
  state: StoryMapState,
  momentId: string,
  stopId: string,
  dayId: string,
): StoryMapState {
  return {
    ...state,
    viewMode: "MOMENT",
    selectedDayId: dayId,
    selectedStopId: stopId,
    selectedMomentId: momentId,
    selectedMediaId: null,
    mapControlMode: "STORY_CONTROLLED",
  };
}

export function selectStoryMedia(
  state: StoryMapState,
  mediaId: string,
  momentId: string,
  stopId: string,
  dayId: string,
): StoryMapState {
  return {
    ...state,
    selectedDayId: dayId,
    selectedStopId: stopId,
    selectedMomentId: momentId,
    selectedMediaId: mediaId,
    mapControlMode: "STORY_CONTROLLED",
  };
}

export function setContributorFilter(
  state: StoryMapState,
  contributorFilter: string,
): StoryMapState {
  return { ...state, contributorFilter, mapControlMode: "STORY_CONTROLLED" };
}

export function markUserControlled(state: StoryMapState): StoryMapState {
  return { ...state, mapControlMode: "USER_CONTROLLED" };
}

export function followStory(state: StoryMapState): StoryMapState {
  return { ...state, mapControlMode: "STORY_CONTROLLED" };
}

export function startPlayback(state: StoryMapState): StoryMapState {
  return { ...state, viewMode: "PLAYBACK", mapControlMode: "STORY_CONTROLLED" };
}

export function advancePlayback(
  state: StoryMapState,
  model: StoryModel,
): StoryMapState {
  const ordered = model.media
    .filter((item) => item.capturedAt)
    .sort((left, right) =>
      String(left.capturedAt).localeCompare(String(right.capturedAt)),
    );
  if (ordered.length === 0) {
    return startPlayback(state);
  }
  const currentIndex = ordered.findIndex(
    (item) => item.id === state.selectedMediaId,
  );
  const next = ordered[(currentIndex + 1) % ordered.length];
  return {
    ...state,
    viewMode: "PLAYBACK",
    selectedDayId: next.dayId,
    selectedStopId: next.stopId,
    selectedMomentId: next.momentId,
    selectedMediaId: next.id,
    timeCursor: next.capturedAt,
    mapControlMode: "STORY_CONTROLLED",
  };
}

export function buildStoryModel(
  reconstruction: ReconstructionResponse | null,
): StoryModel {
  const contributors = new Map<string, string>();
  const stops: StoryStopPoint[] = [];
  const media: StoryMediaPoint[] = [];
  const legs: StoryLegLine[] = [];

  for (const day of reconstruction?.days ?? []) {
    for (const leg of day.legs ?? []) {
      legs.push({
        id: leg.id,
        dayId: day.id,
        fromStopId: leg.fromStopId,
        toStopId: leg.toStopId,
        routeSource: leg.routeSource,
        isForked: Boolean(leg.isForked),
        geometry: isLineString(leg.geometry) ? leg.geometry : null,
      });
    }
    for (const stop of day.stops) {
      stops.push({
        id: stop.id,
        dayId: day.id,
        label: stop.title ?? stop.placeName ?? `Stop ${stop.position}`,
        position: stop.position,
        displayPosition: stop.displayPosition ?? String(stop.position),
        startsAt: stop.startsAt,
        endsAt: stop.endsAt,
        coordinates:
          typeof stop.longitude === "number" &&
          typeof stop.latitude === "number"
            ? [stop.longitude, stop.latitude]
            : null,
      });
      for (const moment of stop.moments) {
        for (const item of moment.media ?? []) {
          contributors.set(item.contributorMemberId, item.contributor);
          media.push({
            id: item.id,
            dayId: day.id,
            stopId: stop.id,
            momentId: moment.id,
            contributorMemberId: item.contributorMemberId,
            contributor: item.contributor,
            capturedAt: item.capturedAt ?? null,
            filename: item.filename ?? null,
            thumbnailUrl: item.thumbnailUrl ?? null,
            previewUrl: item.previewUrl ?? null,
            coordinates:
              typeof item.longitude === "number" &&
              typeof item.latitude === "number"
                ? [item.longitude, item.latitude]
                : null,
          });
        }
      }
    }
  }

  return {
    contributors: Array.from(contributors, ([id, name]) => ({ id, name })).sort(
      (a, b) => a.name.localeCompare(b.name),
    ),
    stops,
    media,
    legs,
    stacks: buildPhotoStacks(media),
  };
}

export function filterStoryModel(
  model: StoryModel,
  contributorFilter: string,
): StoryModel {
  if (contributorFilter === EVERYONE) {
    return model;
  }
  const media = model.media.filter(
    (item) => item.contributorMemberId === contributorFilter,
  );
  const activeStopIds = new Set(media.map((item) => item.stopId));
  const stops = model.stops.filter((stop) => activeStopIds.has(stop.id));
  return {
    ...model,
    stops,
    media,
    legs: model.legs.filter(
      (leg) =>
        activeStopIds.has(leg.fromStopId) && activeStopIds.has(leg.toStopId),
    ),
    stacks: buildPhotoStacks(media),
  };
}

function buildPhotoStacks(media: StoryMediaPoint[]): StoryPhotoStack[] {
  const groups = new Map<string, StoryMediaPoint[]>();
  for (const item of media) {
    if (!item.coordinates) {
      continue;
    }
    const [longitude, latitude] = item.coordinates;
    const key = `${latitude.toFixed(4)},${longitude.toFixed(4)}`;
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return Array.from(groups.entries())
    .filter(([, items]) => items.length > 1)
    .map(([key, items]) => ({
      id: key,
      coordinates: items[0].coordinates as [number, number],
      mediaIds: items.map((item) => item.id),
    }));
}

function isLineString(value: unknown): value is GeoJsonLineString {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as { type?: unknown }).type === "LineString" &&
    Array.isArray((value as { coordinates?: unknown }).coordinates)
  );
}
