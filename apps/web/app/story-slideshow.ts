import type {
  PublicStoryResponse,
  ReconstructionDayResponse,
  ReconstructionLegResponse,
  ReconstructionMediaResponse,
  ReconstructionResponse,
  ReconstructionStopResponse,
} from "./api-types";

export type SlideshowPhoto = {
  id: string;
  imageUrl: string;
  thumbnailUrl: string | null;
  filename: string | null;
  contributor: string;
  capturedAt: string | null;
  capturedAtLocal: string | null;
  dayLabel: string;
  stopLabel: string;
};

export type SlideshowStop = {
  id: string;
  label: string;
  position: number;
  coordinates: [number, number] | null;
  photoCount: number;
};

export type SlideshowRoute = {
  id: string;
  coordinates: [number, number][];
};

export type SlideshowDayMarker = {
  id: string;
  label: string;
  coordinates: [number, number];
  imageUrl: string;
};

export type SlideshowScene =
  | {
      id: string;
      type: "trip";
      durationMs: number;
      title: string;
      subtitle: string;
      stops: SlideshowStop[];
      routes: SlideshowRoute[];
      dayMarkers: SlideshowDayMarker[];
      photoCount: number;
    }
  | {
      id: string;
      type: "day";
      durationMs: number;
      title: string;
      subtitle: string;
      stops: SlideshowStop[];
      routes: SlideshowRoute[];
      photoCount: number;
    }
  | {
      id: string;
      type: "stop";
      durationMs: number;
      title: string;
      subtitle: string;
      dayLabel: string;
      stops: SlideshowStop[];
      routes: SlideshowRoute[];
      activeStopId: string;
      photoCount: number;
    }
  | {
      id: string;
      type: "photo";
      durationMs: number;
      photo: SlideshowPhoto;
    };

export function buildPublicStorySlideshowPhotos(
  story: PublicStoryResponse,
): SlideshowPhoto[] {
  return buildPublicStorySlideshowScenes(story).flatMap((scene) =>
    scene.type === "photo" ? [scene.photo] : [],
  );
}

export function buildPublicStorySlideshowScenes(
  story: PublicStoryResponse,
): SlideshowScene[] {
  return buildReconstructionSlideshowScenes(story.story);
}

export function buildReconstructionSlideshowScenes(
  reconstruction: ReconstructionResponse | null,
): SlideshowScene[] {
  const days = reconstruction?.days ?? [];
  const dayScenes = days.flatMap((day) => {
    const dayStops = day.stops.map((stop) => slideshowStop(stop));
    const dayRoutes = (day.legs ?? []).flatMap((leg) => slideshowRoute(leg));
    const stopSections = day.stops
      .map((stop) => ({
        stop,
        photos: slideshowStopPhotos(day, stop),
      }))
      .filter((section) => section.photos.length > 0);
    const photoCount = stopSections.reduce(
      (total, section) => total + section.photos.length,
      0,
    );
    if (photoCount === 0) {
      return [];
    }
    return [
      {
        id: `day:${day.id}`,
        type: "day" as const,
        durationMs: 5600,
        title: slideshowDayLabel(day),
        subtitle: `${dayStops.length} stop${dayStops.length === 1 ? "" : "s"} · ${photoCount} photo${photoCount === 1 ? "" : "s"}`,
        stops: dayStops,
        routes: dayRoutes,
        photoCount,
      },
      ...stopSections.flatMap(({ stop, photos }) => [
        {
          id: `stop:${stop.id}`,
          type: "stop" as const,
          durationMs: 4600,
          title: slideshowStopLabel(stop),
          subtitle: `${photos.length} photo${photos.length === 1 ? "" : "s"}`,
          dayLabel: slideshowDayLabel(day),
          stops: dayStops,
          routes: dayRoutes,
          activeStopId: stop.id,
          photoCount: photos.length,
        },
        ...photos.map((photo) => ({
          id: `photo:${photo.id}`,
          type: "photo" as const,
          durationMs: 6500,
          photo,
        })),
      ]),
    ];
  });
  if (dayScenes.length === 0) {
    return [];
  }

  const tripStops = days.flatMap((day) =>
    day.stops.map((stop) => slideshowStop(stop)),
  );
  const tripDayMarkers = days.flatMap((day) => {
    const marker = slideshowDayMarker(day);
    return marker ? [marker] : [];
  });
  const photoCount = dayScenes.reduce(
    (total, scene) => total + (scene.type === "photo" ? 1 : 0),
    0,
  );
  return [
    {
      id: "trip:overview",
      type: "trip",
      durationMs: 6200,
      title: "Trip overview",
      subtitle: `${days.length} day${days.length === 1 ? "" : "s"} · ${tripStops.length} stop${tripStops.length === 1 ? "" : "s"} · ${photoCount} photo${photoCount === 1 ? "" : "s"}`,
      stops: tripStops,
      routes: [],
      dayMarkers: tripDayMarkers,
      photoCount,
    },
    ...dayScenes,
  ];
}

function slideshowStopPhotos(
  day: ReconstructionDayResponse,
  stop: ReconstructionStopResponse,
): SlideshowPhoto[] {
  return stop.moments.flatMap((moment) =>
    moment.media.flatMap((media) => {
      const photo = slideshowPhoto(day, stop, media);
      return photo ? [photo] : [];
    }),
  );
}

function slideshowDayMarker(
  day: ReconstructionDayResponse,
): SlideshowDayMarker | null {
  const coordinates = centerOfCoordinates(
    day.stops
      .map((stop) => slideshowStop(stop).coordinates)
      .filter((coordinate) => coordinate !== null),
  );
  const photo = day.stops
    .flatMap((stop) => slideshowStopPhotos(day, stop))
    .at(0);
  if (!coordinates || !photo) {
    return null;
  }
  return {
    id: day.id,
    label: slideshowDayLabel(day),
    coordinates,
    imageUrl: photo.imageUrl,
  };
}

function slideshowPhoto(
  day: ReconstructionDayResponse,
  stop: ReconstructionStopResponse,
  media: ReconstructionMediaResponse,
): SlideshowPhoto | null {
  const imageUrl = media.previewUrl ?? media.thumbnailUrl;
  if (!imageUrl) {
    return null;
  }
  return {
    id: media.id,
    imageUrl,
    thumbnailUrl: media.thumbnailUrl ?? null,
    filename: media.filename ?? null,
    contributor: media.contributor,
    capturedAt: media.capturedAt ?? null,
    capturedAtLocal: media.capturedAtLocal ?? null,
    dayLabel: slideshowDayLabel(day),
    stopLabel: slideshowStopLabel(stop),
  };
}

function slideshowStop(stop: ReconstructionStopResponse): SlideshowStop {
  return {
    id: stop.id,
    label: slideshowStopLabel(stop),
    position: stop.position,
    coordinates:
      typeof stop.longitude === "number" && typeof stop.latitude === "number"
        ? [stop.longitude, stop.latitude]
        : null,
    photoCount: stop.mediaCount,
  };
}

function slideshowRoute(leg: ReconstructionLegResponse): SlideshowRoute[] {
  const coordinates = lineStringCoordinates(leg.geometry);
  return coordinates.length > 1 ? [{ id: leg.id, coordinates }] : [];
}

function lineStringCoordinates(
  geometry: Record<string, unknown> | null | undefined,
): [number, number][] {
  if (
    !geometry ||
    geometry.type !== "LineString" ||
    !Array.isArray(geometry.coordinates)
  ) {
    return [];
  }
  return geometry.coordinates
    .map((coordinate) =>
      Array.isArray(coordinate) &&
      typeof coordinate[0] === "number" &&
      typeof coordinate[1] === "number"
        ? ([coordinate[0], coordinate[1]] as [number, number])
        : null,
    )
    .filter((coordinate) => coordinate !== null);
}

function centerOfCoordinates(
  coordinates: [number, number][],
): [number, number] | null {
  if (coordinates.length === 0) {
    return null;
  }
  const [longitude, latitude] = coordinates.reduce(
    ([longitudeTotal, latitudeTotal], [longitude, latitude]) => [
      longitudeTotal + longitude,
      latitudeTotal + latitude,
    ],
    [0, 0],
  );
  return [longitude / coordinates.length, latitude / coordinates.length];
}

function slideshowDayLabel(day: ReconstructionDayResponse): string {
  return (
    day.title?.trim() ||
    shortCalendarDate(day.date ?? null) ||
    `Day ${day.position}`
  );
}

function slideshowStopLabel(stop: ReconstructionStopResponse): string {
  return (
    stop.title?.trim() || stop.placeName?.trim() || `Stop ${stop.position}`
  );
}

function shortCalendarDate(value: string | null): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value ?? "");
  if (!match) {
    return "";
  }
  const [, year, month, day] = match;
  const date = new Date(Number(year), Number(month) - 1, Number(day));
  return new Intl.DateTimeFormat(undefined, {
    month: "numeric",
    day: "numeric",
  }).format(date);
}
