import type { PublicStoryResponse } from "./api-types";
import { uiLocale } from "./i18n";
import {
  buildPublicStorySlideshowScenes,
  type SlideshowRoute,
  type SlideshowScene,
  type SlideshowStop,
} from "./story-slideshow";

export type FrameStop = {
  id: string;
  label: string;
  position: number;
  x: number;
  y: number;
  active: boolean;
};

export type FrameRoute = {
  id: string;
  points: string;
};

export type FrameScene = {
  id: string;
  type: "map" | "photo";
  title: string;
  subtitle: string;
  durationMs: number;
  imageUrl?: string;
  stops: FrameStop[];
  routes: FrameRoute[];
};

export type FrameStory = {
  title: string;
  subtitle: string;
  timezoneId: string;
  scenes: FrameScene[];
};

export function frameStoryApiBaseUrl(
  internalUrl = process.env.API_INTERNAL_URL,
  publicUrl = process.env.NEXT_PUBLIC_API_BASE_URL,
): string {
  return (internalUrl || publicUrl || "http://localhost:8000").replace(
    /\/$/,
    "",
  );
}

export function publicStoryEndpoint(
  baseUrl: string,
  slug: string,
  versionNumber?: number,
): string {
  const storyPath = `${baseUrl}/public/stories/${encodeURIComponent(slug)}`;
  return versionNumber === undefined
    ? storyPath
    : `${storyPath}/versions/${versionNumber}`;
}

export function buildFrameStory(story: PublicStoryResponse): FrameStory {
  const trip = story.trip as {
    title?: unknown;
    description?: unknown;
    timezoneId?: unknown;
  };
  const title =
    typeof trip.title === "string" && trip.title.trim()
      ? trip.title
      : story.version.title || "Trip story";
  const description =
    typeof trip.description === "string" && trip.description.trim()
      ? trip.description
      : `Published version ${story.version.versionNumber}`;
  const timezoneId =
    typeof trip.timezoneId === "string" && trip.timezoneId.trim()
      ? trip.timezoneId
      : "UTC";

  return {
    title,
    subtitle: description,
    timezoneId,
    scenes: buildPublicStorySlideshowScenes(story).map(frameScene),
  };
}

function frameScene(scene: SlideshowScene): FrameScene {
  if (scene.type === "photo") {
    return {
      id: scene.id,
      type: "photo",
      title: scene.photo.stopLabel,
      subtitle: `${dateLabel(scene.photo.capturedAt)} · ${scene.photo.contributor}`,
      durationMs: scene.durationMs,
      imageUrl: scene.photo.imageUrl,
      stops: [],
      routes: [],
    };
  }

  return {
    id: scene.id,
    type: "map",
    title: scene.title,
    subtitle: scene.subtitle,
    durationMs: scene.durationMs,
    stops: projectStops(
      scene.stops,
      scene.routes,
      scene.type === "stop" ? scene.activeStopId : null,
    ),
    routes: projectRoutes(scene.routes, scene.stops),
  };
}

function projectStops(
  stops: SlideshowStop[],
  routes: SlideshowRoute[],
  activeStopId: string | null,
): FrameStop[] {
  const bounds = coordinateBounds(stops, routes);
  return stops.map((stop) => {
    const point = stop.coordinates
      ? projectCoordinate(stop.coordinates, bounds)
      : { x: 50, y: 50 };
    return {
      id: stop.id,
      label: stop.label,
      position: stop.position,
      x: point.x,
      y: point.y,
      active: activeStopId === stop.id,
    };
  });
}

function projectRoutes(
  routes: SlideshowRoute[],
  stops: SlideshowStop[],
): FrameRoute[] {
  const bounds = coordinateBounds(stops, routes);
  return routes
    .map((route) => ({
      id: route.id,
      points: route.coordinates
        .map((coordinate) => {
          const point = projectCoordinate(coordinate, bounds);
          return `${round(point.x)},${round(point.y)}`;
        })
        .join(" "),
    }))
    .filter((route) => route.points.length > 0);
}

function coordinateBounds(
  stops: SlideshowStop[],
  routes: SlideshowRoute[],
): {
  minLongitude: number;
  maxLongitude: number;
  minLatitude: number;
  maxLatitude: number;
} {
  const coordinates = [
    ...stops.flatMap((stop) => (stop.coordinates ? [stop.coordinates] : [])),
    ...routes.flatMap((route) => route.coordinates),
  ];
  if (coordinates.length === 0) {
    return {
      minLongitude: 0,
      maxLongitude: 0,
      minLatitude: 0,
      maxLatitude: 0,
    };
  }
  const longitudes = coordinates.map((coordinate) => coordinate[0]);
  const latitudes = coordinates.map((coordinate) => coordinate[1]);
  return {
    minLongitude: Math.min(...longitudes),
    maxLongitude: Math.max(...longitudes),
    minLatitude: Math.min(...latitudes),
    maxLatitude: Math.max(...latitudes),
  };
}

function projectCoordinate(
  coordinate: [number, number],
  bounds: ReturnType<typeof coordinateBounds>,
): { x: number; y: number } {
  const longitudeSpan = bounds.maxLongitude - bounds.minLongitude;
  const latitudeSpan = bounds.maxLatitude - bounds.minLatitude;
  const x =
    longitudeSpan === 0
      ? 50
      : 10 + ((coordinate[0] - bounds.minLongitude) / longitudeSpan) * 80;
  const y =
    latitudeSpan === 0
      ? 50
      : 85 - ((coordinate[1] - bounds.minLatitude) / latitudeSpan) * 70;
  return { x: round(x), y: round(y) };
}

function dateLabel(value: string | null): string {
  if (!value) {
    return "Trip photo";
  }
  try {
    return new Intl.DateTimeFormat(uiLocale(), {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }).format(new Date(value));
  } catch {
    return "Trip photo";
  }
}

function round(value: number): number {
  return Math.round(value * 10) / 10;
}
