"use client";

import {
  ChangeEvent,
  DragEvent,
  FormEvent,
  Fragment,
  KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import maplibregl, {
  GeoJSONSource,
  LngLatBounds,
  Map as MapLibreMap,
  Marker,
} from "maplibre-gl";
import QRCode from "qrcode";
import { ApiError, api, guestApi, uploadWithProgress } from "./api-client";
import type {
  AreaVisitResponse,
  AreaVisitsResponse,
  GuestMemberResponse,
  InvitationPreviewResponse,
  InvitationResponse,
  ReconstructionDayResponse,
  MediaItemResponse,
  MemberResponse,
  PublicationsListResponse,
  PublicStoryResponse,
  ReconstructionResponse,
  ReconstructionStopResponse,
  SimilarityGroupResponse,
  StoryPhotoProjectionResponse,
  StoryPhotoProjectionPhotoResponse,
  TripResponse,
  UploadFileResponse,
  UploadSessionResponse,
  UserResponse,
} from "./api-types";
import {
  buildReconstructionSlideshowScenes,
  buildPublicStorySlideshowScenes,
  type SlideshowScene,
  type SlideshowPhoto,
  type SlideshowRoute,
} from "./story-slideshow";
import {
  EVERYONE,
  StoryMapState,
  type StoryLegLine,
  type StoryMediaPoint,
  type StoryStopPoint,
  ViewMode,
  advancePlayback,
  buildStoryModel,
  filterStoryModel,
  followStory,
  initialStoryMapState,
  markUserControlled,
  normalizeStoryMapState,
  selectStoryDay,
  selectStoryMedia,
  selectStoryStop,
  setContributorFilter,
  startPlayback,
} from "./story-map-state";

type GalleryPhoto = {
  id: string;
  imageUrl: string | null;
  thumbnailUrl: string | null;
  filename: string | null;
  contributor: string;
  capturedAt: string | null;
  contextLabel?: string | null;
};

type AuthMode = "login" | "register";
type LoadState = "loading" | "ready";
type MobileWorkspaceTab =
  "story" | "timeline" | "photos" | "share" | "tripSettings" | "appSettings";
type StoryMobilePane = "map" | "timeline" | "photos";
type StoryHeaderIconAction =
  | StoryMobilePane
  | "story"
  | "slideshow"
  | "share"
  | "more"
  | "update"
  | "upload"
  | "manage"
  | "settings";

type TripForm = {
  title: string;
  description: string;
  startDate: string;
  endDate: string;
  timezoneId: string;
  dayCutoffHour: string;
};

type UploadProgress = {
  loaded: number;
  total: number;
  status: "pending" | "uploading" | "complete" | "failed" | "cancelled";
  error?: string;
};

function renameStopInReconstruction(
  reconstruction: ReconstructionResponse | null,
  stopId: string,
  title: string,
): ReconstructionResponse | null {
  if (!reconstruction) {
    return reconstruction;
  }
  let renamed = false;
  const days = reconstruction.days.map((day) => {
    let renamedInDay = false;
    const stops = day.stops.map((stop) => {
      if (stop.id !== stopId) {
        return stop;
      }
      renamed = true;
      renamedInDay = true;
      return { ...stop, title };
    });
    return renamedInDay ? { ...day, stops } : day;
  });
  return renamed ? { ...reconstruction, days } : reconstruction;
}

type IntlWithTimeZones = typeof Intl & {
  supportedValuesOf?: (key: "timeZone") => string[];
};

const fallbackTimeZones = [
  "UTC",
  "America/Los_Angeles",
  "America/Denver",
  "America/Chicago",
  "America/New_York",
  "Europe/London",
  "Europe/Paris",
  "Europe/Rome",
  "Asia/Seoul",
  "Asia/Tokyo",
  "Asia/Taipei",
  "Asia/Hong_Kong",
  "Asia/Singapore",
  "Australia/Sydney",
  "Pacific/Auckland",
];

function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

function supportedTimeZones(): string[] {
  try {
    const zones = (Intl as IntlWithTimeZones).supportedValuesOf?.("timeZone");
    return zones && zones.length > 0 ? zones : fallbackTimeZones;
  } catch {
    return fallbackTimeZones;
  }
}

function timeZoneOptions(currentValue: string): string[] {
  return Array.from(
    new Set(["UTC", browserTimeZone(), currentValue, ...supportedTimeZones()]),
  )
    .filter(Boolean)
    .sort((left, right) => left.localeCompare(right));
}

function isSupportedTimeZone(value: string): boolean {
  if (!value) {
    return false;
  }
  try {
    new Intl.DateTimeFormat(undefined, { timeZone: value });
    return true;
  } catch {
    return false;
  }
}

const emptyTripForm: TripForm = {
  title: "",
  description: "",
  startDate: "",
  endDate: "",
  timezoneId: browserTimeZone(),
  dayCutoffHour: "4",
};

function messageFrom(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Something went wrong";
}

function toPayload(form: TripForm) {
  return {
    title: form.title,
    description: form.description || null,
    startDate: form.startDate || null,
    endDate: form.endDate || null,
    timezoneId: form.timezoneId,
    dayCutoffHour: Number(form.dayCutoffHour),
  };
}

function fromTrip(trip: TripResponse): TripForm {
  return {
    title: trip.title,
    description: trip.description ?? "",
    startDate: trip.startDate ?? "",
    endDate: trip.endDate ?? "",
    timezoneId: trip.timezoneId,
    dayCutoffHour: String(trip.dayCutoffHour),
  };
}

function stringHeaders(
  headers: Record<string, unknown>,
): Record<string, string> {
  return Object.fromEntries(
    Object.entries(headers).filter(
      (entry): entry is [string, string] => typeof entry[1] === "string",
    ),
  );
}

function uploadMimeType(file: File): string {
  const explicitType = file.type.trim().toLowerCase();
  if (explicitType && explicitType !== "application/octet-stream") {
    return explicitType;
  }
  const filename = file.name.toLowerCase();
  if (filename.endsWith(".heic")) {
    return "image/heic";
  }
  if (filename.endsWith(".heif")) {
    return "image/heif";
  }
  if (filename.endsWith(".jpg") || filename.endsWith(".jpeg")) {
    return "image/jpeg";
  }
  return explicitType || "application/octet-stream";
}

export default function TripWeaveApp() {
  const [path] = useState(() =>
    typeof window === "undefined" ? "/" : window.location.pathname,
  );
  if (path.startsWith("/invite/")) {
    return (
      <InviteAcceptance
        token={decodeURIComponent(path.slice("/invite/".length))}
      />
    );
  }
  if (path.startsWith("/contribute/")) {
    return (
      <ContributorWorkspace
        tripId={decodeURIComponent(path.slice("/contribute/".length))}
      />
    );
  }
  if (path.startsWith("/story/")) {
    const storyPath = path.slice("/story/".length);
    const slideshowSuffix = "/slideshow";
    const isSlideshow = storyPath.endsWith(slideshowSuffix);
    const tokenPath = isSlideshow
      ? storyPath.slice(0, -slideshowSuffix.length)
      : storyPath;
    return (
      <PublicStoryViewer
        token={decodeURIComponent(tokenPath)}
        initialView={isSlideshow ? "slideshow" : "story"}
      />
    );
  }
  return <OwnerWorkspace />;
}

function OwnerWorkspace() {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [user, setUser] = useState<UserResponse | null>(null);
  const [trips, setTrips] = useState<TripResponse[]>([]);
  const [selectedTripId, setSelectedTripId] = useState<string | null>(null);
  const selectedTripIdRef = useRef<string | null>(null);
  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [authError, setAuthError] = useState("");
  const [tripError, setTripError] = useState("");
  const [createForm, setCreateForm] = useState<TripForm>(emptyTripForm);
  const [settingsForm, setSettingsForm] = useState<TripForm>(emptyTripForm);
  const [isBusy, setIsBusy] = useState(false);
  const [isReconstructingStory, setIsReconstructingStory] = useState(false);
  const [uploadSessions, setUploadSessions] = useState<UploadSessionResponse[]>(
    [],
  );
  const [uploadError, setUploadError] = useState("");
  const [media, setMedia] = useState<MediaItemResponse[]>([]);
  const [similarityGroups, setSimilarityGroups] = useState<
    SimilarityGroupResponse[]
  >([]);
  const [mediaError, setMediaError] = useState("");
  const [reconstruction, setReconstruction] =
    useState<ReconstructionResponse | null>(null);
  const [storyProjection, setStoryProjection] =
    useState<ReconstructionResponse | null>(null);
  const [storyDataTripId, setStoryDataTripId] = useState<string | null>(null);
  const [isStoryProjectionLoading, setIsStoryProjectionLoading] =
    useState(false);
  const [reconstructionError, setReconstructionError] = useState("");
  const [reviewIndex, setReviewIndex] = useState(0);
  const [storyState, setStoryState] = useState<StoryMapState>(() =>
    initialStoryMapState(),
  );
  const [invitations, setInvitations] = useState<InvitationResponse[]>([]);
  const [members, setMembers] = useState<MemberResponse[]>([]);
  const [collaborationError, setCollaborationError] = useState("");
  const [publications, setPublications] =
    useState<PublicationsListResponse | null>(null);
  const [publicationError, setPublicationError] = useState("");
  const [latestShareUrl, setLatestShareUrl] = useState("");
  const [latestInviteUrl, setLatestInviteUrl] = useState("");
  const [latestInviteQrUrl, setLatestInviteQrUrl] = useState("");
  const [mobileTab, setMobileTab] = useState<MobileWorkspaceTab>("story");
  const [mobileTripMenuOpen, setMobileTripMenuOpen] = useState(false);
  const [ownerStoryPhotosOpen, setOwnerStoryPhotosOpen] = useState(false);
  const [ownerSlideshowOpen, setOwnerSlideshowOpen] = useState(false);
  const isMobileWorkspace = useMediaQuery("(max-width: 920px)");
  const [uploadProgress, setUploadProgress] = useState<
    Record<string, UploadProgress>
  >({});
  const localFiles = useRef<Map<string, File>>(new Map());
  const abortUpload = useRef<Map<string, () => void>>(new Map());

  const selectedTrip = useMemo(
    () => trips.find((trip) => trip.id === selectedTripId) ?? trips[0] ?? null,
    [selectedTripId, trips],
  );
  const canOrganizeSelectedTrip =
    selectedTrip !== null && ["owner", "editor"].includes(selectedTrip.role);
  const selectedTripHasStoryData =
    selectedTrip !== null && storyDataTripId === selectedTrip.id;
  const storyForExplorer = selectedTripHasStoryData
    ? (reconstruction ?? storyProjection)
    : null;
  const isStoryExplorerLoading =
    selectedTrip !== null &&
    isStoryProjectionLoading &&
    !selectedTripHasStoryData;
  const storyUpdate = storyForExplorer?.storyUpdate ?? null;
  const storyUpdateNeeded = Boolean(storyUpdate?.needsUpdate);
  const storyUpdateLabel = storyUpdate
    ? storyUpdate.unassignedReadyMediaCount > 0
      ? `${storyUpdate.unassignedReadyMediaCount} new photo${
          storyUpdate.unassignedReadyMediaCount === 1 ? "" : "s"
        } need update`
      : "Story is up to date"
    : "";
  const storyActionButtonLabel = isReconstructingStory
    ? "Updating story..."
    : "Update story";
  const storyActionStatusLabel = isReconstructingStory
    ? "Rebuilding map and timeline..."
    : storyUpdateLabel;
  const isStoryActionDisabled = isBusy || isReconstructingStory;
  const storyActionTitle = isReconstructingStory
    ? "Updating story..."
    : storyUpdate
      ? storyActionStatusLabel
      : "Update story";
  const ownerSlideshowScenes = useMemo(
    () => buildReconstructionSlideshowScenes(storyForExplorer),
    [storyForExplorer],
  );
  const canOpenOwnerSlideshow =
    Boolean(storyForExplorer?.latestRun) && ownerSlideshowScenes.length > 0;

  const selectedUploadFiles = useMemo(
    () => uploadSessions.flatMap((session) => session.files),
    [uploadSessions],
  );

  const hasProcessingMedia = useMemo(
    () =>
      media.some((item) =>
        ["pending", "processing"].includes(item.processingState),
      ),
    [media],
  );
  const openReviewCount =
    reconstruction?.reviewItems.filter((item) => item.status === "open")
      .length ?? 0;
  const activeMemberCount = members.filter(
    (member) => !member.removedAt,
  ).length;
  const activeShareCount =
    publications?.shareLinks.filter((link) => link.status === "active")
      .length ?? 0;
  const canManageSelectedTrip = Boolean(
    selectedTrip && ["owner", "editor"].includes(selectedTrip.role),
  );

  const setSelectedTripSelection = useCallback((tripId: string | null) => {
    selectedTripIdRef.current = tripId;
    setSelectedTripId(tripId);
  }, []);

  const loadTrips = useCallback(
    async (preferredTripId: string | null = null) => {
      const result = await api.trips();
      setTrips(result.trips);
      const next =
        preferredTripId &&
        result.trips.some((trip) => trip.id === preferredTripId)
          ? preferredTripId
          : (result.trips[0]?.id ?? null);
      const nextTrip = result.trips.find((trip) => trip.id === next) ?? null;
      setSelectedTripSelection(next);
      setSettingsForm(nextTrip ? fromTrip(nextTrip) : emptyTripForm);
      setReconstruction(null);
      setStoryProjection(null);
      setStoryDataTripId(null);
      setIsStoryProjectionLoading(Boolean(next));
      setStoryState(initialStoryMapState());
    },
    [setSelectedTripSelection],
  );

  const loadUploadSessions = useCallback(async (tripId: string | null) => {
    if (!tripId) {
      setUploadSessions([]);
      return;
    }
    const result = await api.uploadSessions(tripId);
    setUploadSessions(result.uploadSessions);
  }, []);

  const loadMedia = useCallback(async (tripId: string | null) => {
    if (!tripId) {
      setMedia([]);
      setSimilarityGroups([]);
      return;
    }
    const [result, groupResult] = await Promise.all([
      api.media(tripId),
      api.similarityGroups(tripId),
    ]);
    setMedia(result.media);
    setSimilarityGroups(groupResult.groups);
  }, []);

  const loadReconstruction = useCallback(async (tripId: string | null) => {
    if (!tripId) {
      setReconstruction(null);
      setStoryProjection(null);
      setStoryDataTripId(null);
      setIsStoryProjectionLoading(false);
      return;
    }
    if (selectedTripIdRef.current === tripId) {
      setIsStoryProjectionLoading(true);
    }
    try {
      const result = await api.reconstruction(tripId);
      if (selectedTripIdRef.current !== tripId) {
        return;
      }
      setReconstruction(result);
      setStoryProjection(result);
      setStoryDataTripId(tripId);
    } finally {
      if (selectedTripIdRef.current === tripId) {
        setIsStoryProjectionLoading(false);
      }
    }
  }, []);

  const loadStoryProjection = useCallback(async (tripId: string | null) => {
    if (!tripId) {
      setStoryProjection(null);
      setStoryDataTripId(null);
      setIsStoryProjectionLoading(false);
      return;
    }
    if (selectedTripIdRef.current === tripId) {
      setIsStoryProjectionLoading(true);
    }
    try {
      const result = await api.storyDraftProjection(tripId);
      if (selectedTripIdRef.current !== tripId) {
        return;
      }
      setReconstruction(null);
      setStoryProjection(result);
      setStoryDataTripId(tripId);
    } finally {
      if (selectedTripIdRef.current === tripId) {
        setIsStoryProjectionLoading(false);
      }
    }
  }, []);

  const loadCollaboration = useCallback(async (tripId: string | null) => {
    if (!tripId) {
      setInvitations([]);
      setMembers([]);
      return;
    }
    const [inviteResult, memberResult] = await Promise.all([
      api.invitations(tripId),
      api.members(tripId),
    ]);
    setInvitations(inviteResult.invitations);
    setMembers(memberResult.members);
  }, []);

  const loadPublications = useCallback(async (tripId: string | null) => {
    if (!tripId) {
      setPublications(null);
      return;
    }
    setPublications(await api.publications(tripId));
  }, []);

  function selectTrip(trip: TripResponse) {
    setOwnerSlideshowOpen(false);
    setSelectedTripSelection(trip.id);
    setSettingsForm(fromTrip(trip));
    setReconstruction(null);
    setStoryProjection(null);
    setStoryDataTripId(null);
    setIsStoryProjectionLoading(true);
    setStoryState(initialStoryMapState());
    setReconstructionError("");
    void loadUploadSessions(trip.id);
    void loadMedia(trip.id);
    void loadStoryProjection(trip.id);
    if (trip.role === "owner") {
      void loadCollaboration(trip.id);
    } else {
      setInvitations([]);
      setMembers([]);
    }
    if (["owner", "editor"].includes(trip.role)) {
      void loadPublications(trip.id);
    } else {
      setPublications(null);
    }
  }

  function removeTripFromState(tripId: string) {
    setOwnerSlideshowOpen(false);
    const remaining = trips.filter((trip) => trip.id !== tripId);
    const nextTrip = remaining[0] ?? null;
    setTrips(remaining);
    setSelectedTripSelection(nextTrip?.id ?? null);
    setSettingsForm(nextTrip ? fromTrip(nextTrip) : emptyTripForm);
    setReconstruction(null);
    setStoryProjection(null);
    setStoryDataTripId(null);
    setStoryState(initialStoryMapState());
    setIsStoryProjectionLoading(Boolean(nextTrip));
    if (!nextTrip) {
      setUploadSessions([]);
      setMedia([]);
      setSimilarityGroups([]);
      setInvitations([]);
      setMembers([]);
      setPublications(null);
      setLatestShareUrl("");
    }
  }

  function addTripToState(trip: TripResponse) {
    setTrips((current) => [trip, ...current]);
    selectTrip(trip);
  }

  function updateTripInState(updated: TripResponse) {
    setTrips((current) =>
      current.map((trip) => (trip.id === updated.id ? updated : trip)),
    );
    setSettingsForm(fromTrip(updated));
  }

  useEffect(() => {
    let cancelled = false;
    async function loadSession() {
      try {
        const result = await api.me();
        if (cancelled) {
          return;
        }
        setUser(result.user);
        const preferredTripId =
          typeof window === "undefined"
            ? null
            : new URLSearchParams(window.location.search).get("tripId");
        await loadTrips(preferredTripId);
      } catch {
        if (!cancelled) {
          setUser(null);
        }
      } finally {
        if (!cancelled) {
          setLoadState("ready");
        }
      }
    }
    void loadSession();
    return () => {
      cancelled = true;
    };
  }, [loadTrips]);

  useEffect(() => {
    if (selectedTrip?.id) {
      void Promise.resolve().then(() =>
        loadUploadSessions(selectedTrip.id).catch((error) =>
          setUploadError(messageFrom(error)),
        ),
      );
    }
  }, [loadUploadSessions, selectedTrip?.id]);

  useEffect(() => {
    if (selectedTrip?.id) {
      void Promise.resolve().then(() =>
        loadStoryProjection(selectedTrip.id).catch((error) =>
          setReconstructionError(messageFrom(error)),
        ),
      );
    }
  }, [loadStoryProjection, selectedTrip?.id]);

  useEffect(() => {
    if (selectedTrip?.id && selectedTrip.role === "owner") {
      void Promise.resolve().then(() =>
        loadCollaboration(selectedTrip.id).catch((error) =>
          setCollaborationError(messageFrom(error)),
        ),
      );
    }
  }, [loadCollaboration, selectedTrip?.id, selectedTrip?.role]);

  useEffect(() => {
    if (selectedTrip?.id && ["owner", "editor"].includes(selectedTrip.role)) {
      void Promise.resolve().then(() =>
        loadPublications(selectedTrip.id).catch((error) =>
          setPublicationError(messageFrom(error)),
        ),
      );
    }
  }, [loadPublications, selectedTrip?.id, selectedTrip?.role]);

  useEffect(() => {
    let cancelled = false;
    if (!latestInviteUrl) {
      return;
    }
    QRCode.toDataURL(latestInviteUrl, {
      errorCorrectionLevel: "M",
      margin: 1,
      width: 160,
    })
      .then((url) => {
        if (!cancelled) {
          setLatestInviteQrUrl(url);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLatestInviteQrUrl("");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [latestInviteUrl]);

  useEffect(() => {
    if (!selectedTrip?.id) {
      return;
    }
    const tripId = selectedTrip.id;
    let cancelled = false;
    let delay = 1200;
    let timeout: ReturnType<typeof setTimeout> | null = null;
    async function poll() {
      try {
        const result = await api.media(tripId);
        if (cancelled) {
          return;
        }
        setMedia(result.media);
        setMediaError("");
        const keepPolling = result.media.some((item) =>
          ["pending", "processing"].includes(item.processingState),
        );
        if (keepPolling) {
          timeout = setTimeout(poll, delay);
          delay = Math.min(delay * 1.6, 10000);
        } else if (hasProcessingMedia) {
          await loadStoryProjection(tripId);
        }
      } catch (error) {
        if (!cancelled) {
          setMediaError(messageFrom(error));
          timeout = setTimeout(poll, delay);
          delay = Math.min(delay * 1.6, 10000);
        }
      }
    }
    void poll();
    return () => {
      cancelled = true;
      if (timeout) {
        clearTimeout(timeout);
      }
    };
  }, [hasProcessingMedia, loadStoryProjection, selectedTrip?.id]);

  useEffect(() => {
    if (!selectedTrip?.id || !storyUpdateNeeded || isReconstructingStory) {
      return;
    }
    const tripId = selectedTrip.id;
    let cancelled = false;
    let timeout: ReturnType<typeof setTimeout> | null = null;
    async function pollStoryUpdate() {
      try {
        await loadStoryProjection(tripId);
      } catch (error) {
        if (!cancelled) {
          setReconstructionError(messageFrom(error));
        }
      }
      if (!cancelled) {
        timeout = setTimeout(pollStoryUpdate, 8000);
      }
    }
    timeout = setTimeout(pollStoryUpdate, 8000);
    return () => {
      cancelled = true;
      if (timeout) {
        clearTimeout(timeout);
      }
    };
  }, [
    isReconstructingStory,
    loadStoryProjection,
    selectedTrip?.id,
    storyUpdateNeeded,
  ]);

  async function submitAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAuthError("");
    setIsBusy(true);
    try {
      const result =
        mode === "register"
          ? await api.register({ email, password, displayName })
          : await api.login({ email, password });
      setUser(result.user);
      await loadTrips();
      setPassword("");
    } catch (error) {
      setAuthError(messageFrom(error));
    } finally {
      setIsBusy(false);
    }
  }

  async function logout() {
    setIsBusy(true);
    try {
      await api.logout();
      setUser(null);
      setTrips([]);
      setSelectedTripSelection(null);
      setUploadSessions([]);
      setMedia([]);
      setSimilarityGroups([]);
      setReconstruction(null);
      setStoryProjection(null);
      setStoryDataTripId(null);
      setIsStoryProjectionLoading(false);
      setStoryState(initialStoryMapState());
      setInvitations([]);
      setMembers([]);
      setPublications(null);
      setLatestShareUrl("");
    } catch (error) {
      setTripError(messageFrom(error));
    } finally {
      setIsBusy(false);
    }
  }

  async function createTrip(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTripError("");
    setIsBusy(true);
    try {
      const trip = await api.createTrip(toPayload(createForm));
      addTripToState(trip);
      setCreateForm(emptyTripForm);
    } catch (error) {
      setTripError(messageFrom(error));
    } finally {
      setIsBusy(false);
    }
  }

  async function updateTrip(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedTrip) {
      return;
    }
    setTripError("");
    setIsBusy(true);
    try {
      const updated = await api.updateTrip(
        selectedTrip.id,
        toPayload(settingsForm),
      );
      updateTripInState(updated);
    } catch (error) {
      setTripError(messageFrom(error));
    } finally {
      setIsBusy(false);
    }
  }

  async function deleteTrip() {
    if (!selectedTrip) {
      return;
    }
    setTripError("");
    setIsBusy(true);
    try {
      await api.deleteTrip(selectedTrip.id);
      removeTripFromState(selectedTrip.id);
    } catch (error) {
      setTripError(messageFrom(error));
    } finally {
      setIsBusy(false);
    }
  }

  function rememberProgress(fileId: string, next: UploadProgress) {
    setUploadProgress((current) => ({ ...current, [fileId]: next }));
  }

  async function uploadOne(uploadFile: UploadFileResponse, file: File) {
    if (!uploadFile.grant) {
      rememberProgress(uploadFile.id, {
        loaded: 0,
        total: file.size,
        status: "failed",
        error: "Upload grant is unavailable",
      });
      return;
    }
    rememberProgress(uploadFile.id, {
      loaded: 0,
      total: file.size,
      status: "uploading",
    });
    const transfer = uploadWithProgress({
      url: uploadFile.grant.url,
      file,
      headers: stringHeaders(uploadFile.grant.headers),
      onProgress: (loaded, total) =>
        rememberProgress(uploadFile.id, {
          loaded,
          total,
          status: "uploading",
        }),
    });
    abortUpload.current.set(uploadFile.id, transfer.abort);
    try {
      await transfer.promise;
      await api.completeUploadFile(uploadFile.id);
      rememberProgress(uploadFile.id, {
        loaded: file.size,
        total: file.size,
        status: "complete",
      });
    } catch (error) {
      rememberProgress(uploadFile.id, {
        loaded: 0,
        total: file.size,
        status: "failed",
        error: messageFrom(error),
      });
    } finally {
      abortUpload.current.delete(uploadFile.id);
    }
  }

  async function uploadFiles(files: File[]) {
    if (!selectedTrip || files.length === 0) {
      return;
    }
    setUploadError("");
    try {
      const session = await api.createUploadSession(selectedTrip.id, {
        files: files.map((file) => ({
          filename: file.name,
          byteSize: file.size,
          mimeType: uploadMimeType(file),
        })),
      });
      setUploadSessions((current) => [session, ...current]);
      session.files.forEach((uploadFile, index) => {
        const file = files[index];
        if (file) {
          localFiles.current.set(uploadFile.id, file);
          rememberProgress(uploadFile.id, {
            loaded: 0,
            total: file.size,
            status: "pending",
          });
        }
      });

      const queue = [...session.files];
      const workers = Array.from(
        { length: Math.min(3, queue.length) },
        async () => {
          while (queue.length > 0) {
            const uploadFile = queue.shift();
            if (!uploadFile) {
              return;
            }
            const file = localFiles.current.get(uploadFile.id);
            if (file) {
              await uploadOne(uploadFile, file);
            }
          }
        },
      );
      await Promise.all(workers);
      await loadUploadSessions(selectedTrip.id);
      await loadMedia(selectedTrip.id);
      await loadStoryProjection(selectedTrip.id);
    } catch (error) {
      setUploadError(messageFrom(error));
    }
  }

  function onFileInput(event: ChangeEvent<HTMLInputElement>) {
    void uploadFiles(Array.from(event.target.files ?? []));
    event.target.value = "";
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    void uploadFiles(Array.from(event.dataTransfer.files));
  }

  async function retryUpload(
    uploadFile: UploadFileResponse,
    selectedFile?: File,
  ) {
    const file = selectedFile ?? localFiles.current.get(uploadFile.id);
    if (!file) {
      return;
    }
    if (uploadFile.byteSize !== null && file.size !== uploadFile.byteSize) {
      setUploadError(
        "Select the same file size that was registered for this retry.",
      );
      return;
    }
    setUploadError("");
    localFiles.current.set(uploadFile.id, file);
    await uploadOne(uploadFile, file);
    if (selectedTrip) {
      await loadUploadSessions(selectedTrip.id);
      await loadMedia(selectedTrip.id);
    }
  }

  async function cancelUpload(uploadFile: UploadFileResponse) {
    abortUpload.current.get(uploadFile.id)?.();
    rememberProgress(uploadFile.id, {
      loaded: 0,
      total: uploadFile.byteSize ?? 0,
      status: "cancelled",
    });
    await api.cancelUploadFile(uploadFile.id);
    if (selectedTrip) {
      await loadUploadSessions(selectedTrip.id);
      await loadMedia(selectedTrip.id);
    }
  }

  async function retryMedia(item: MediaItemResponse) {
    setMediaError("");
    try {
      await api.retryMedia(item.id);
      if (selectedTrip) {
        await loadMedia(selectedTrip.id);
        await loadStoryProjection(selectedTrip.id);
      }
    } catch (error) {
      setMediaError(messageFrom(error));
    }
  }

  async function updateMediaVisibility(
    item: MediaItemResponse,
    visibility: string,
  ) {
    if (!selectedTrip) {
      return;
    }
    setMediaError("");
    setMedia((current) =>
      current.map((mediaItem) =>
        mediaItem.id === item.id
          ? {
              ...mediaItem,
              visibility,
              includeInStory: visibility === "story",
            }
          : mediaItem,
      ),
    );
    try {
      await api.updateMedia(item.id, {
        visibility,
        includeInStory: visibility === "story",
      });
      await loadMedia(selectedTrip.id);
      await loadStoryProjection(selectedTrip.id);
    } catch (error) {
      setMediaError(messageFrom(error));
      await loadMedia(selectedTrip.id);
    }
  }

  async function createInvite() {
    if (!selectedTrip) {
      return;
    }
    setCollaborationError("");
    try {
      const invitation = await api.createInvitation(selectedTrip.id);
      setLatestInviteQrUrl("");
      setLatestInviteUrl(invitation.inviteUrl ?? "");
      await loadCollaboration(selectedTrip.id);
    } catch (error) {
      setCollaborationError(messageFrom(error));
    }
  }

  async function copyInviteUrl() {
    if (!latestInviteUrl || typeof navigator === "undefined") {
      return;
    }
    await navigator.clipboard.writeText(latestInviteUrl);
  }

  async function copyLatestShareUrl() {
    if (!latestShareUrl || typeof navigator === "undefined") {
      return;
    }
    await navigator.clipboard.writeText(latestShareUrl);
  }

  async function revokeInvite(invitation: InvitationResponse) {
    if (!selectedTrip) {
      return;
    }
    setCollaborationError("");
    try {
      await api.revokeInvitation(invitation.id);
      await loadCollaboration(selectedTrip.id);
    } catch (error) {
      setCollaborationError(messageFrom(error));
    }
  }

  async function removeMember(member: MemberResponse) {
    if (!selectedTrip) {
      return;
    }
    setCollaborationError("");
    try {
      await api.removeMember(member.id);
      await loadCollaboration(selectedTrip.id);
    } catch (error) {
      setCollaborationError(messageFrom(error));
    }
  }

  async function runReconstruction() {
    if (!selectedTrip || isStoryActionDisabled) {
      return;
    }
    setReconstructionError("");
    setIsReconstructingStory(true);
    setIsBusy(true);
    try {
      const result = await api.startReconstruction(selectedTrip.id);
      setReconstruction(result);
      setStoryProjection(result);
      await loadMedia(selectedTrip.id);
    } catch (error) {
      setReconstructionError(messageFrom(error));
    } finally {
      setIsReconstructingStory(false);
      setIsBusy(false);
    }
  }

  function openOwnerStoryPhotos() {
    setOwnerStoryPhotosOpen(true);
  }

  function loadReviewDetails() {
    if (!selectedTrip || reconstruction) {
      return;
    }
    void loadReconstruction(selectedTrip.id).catch((error) =>
      setReconstructionError(messageFrom(error)),
    );
  }

  async function changeSimilarityRepresentative(
    groupId: string,
    mediaId: string,
  ) {
    if (!selectedTrip) {
      return;
    }
    setMediaError("");
    try {
      await api.createEditOperation(selectedTrip.id, {
        operationType: "set_similarity_representative",
        payload: { similarityGroupId: groupId, mediaItemId: mediaId },
      });
      await loadMedia(selectedTrip.id);
    } catch (error) {
      setMediaError(messageFrom(error));
    }
  }

  async function acceptClockOffset(reviewItemId: string) {
    const reviewItem = reconstruction?.reviewItems.find(
      (item) => item.id === reviewItemId,
    );
    const suggestionId = reviewItem?.payload.suggestionId;
    if (!selectedTrip || typeof suggestionId !== "string") {
      return;
    }
    setReconstructionError("");
    setIsBusy(true);
    try {
      await api.createEditOperation(selectedTrip.id, {
        operationType: "accept_clock_offset_suggestion",
        reviewItemId,
        payload: { suggestionId },
      });
      await loadReconstruction(selectedTrip.id);
      await loadMedia(selectedTrip.id);
    } catch (error) {
      setReconstructionError(messageFrom(error));
    } finally {
      setIsBusy(false);
    }
  }

  async function applyReviewDecision(
    reviewItemId: string,
    operationType: "resolve_review_item" | "dismiss_review_item",
  ) {
    if (!selectedTrip) {
      return;
    }
    setReconstructionError("");
    setIsBusy(true);
    try {
      const reviewItem = reconstruction?.reviewItems.find(
        (item) => item.id === reviewItemId,
      );
      const suggestionId = reviewItem?.payload.suggestionId;
      if (
        operationType === "dismiss_review_item" &&
        reviewItem?.itemType === "possible_clock_offset" &&
        typeof suggestionId === "string"
      ) {
        await api.createEditOperation(selectedTrip.id, {
          operationType: "reject_clock_offset_suggestion",
          reviewItemId,
          payload: { suggestionId, resolution: "Rejected by organizer" },
        });
        await loadReconstruction(selectedTrip.id);
        await loadMedia(selectedTrip.id);
        return;
      }
      await api.createEditOperation(selectedTrip.id, {
        operationType,
        reviewItemId,
        payload: {
          reviewItemId,
          resolution:
            operationType === "resolve_review_item"
              ? "Reviewed and accepted"
              : "Dismissed by organizer",
        },
      });
      await loadReconstruction(selectedTrip.id);
      await loadMedia(selectedTrip.id);
    } catch (error) {
      setReconstructionError(messageFrom(error));
    } finally {
      setIsBusy(false);
    }
  }

  async function undoLatestEdit() {
    if (!selectedTrip) {
      return;
    }
    setReconstructionError("");
    setIsBusy(true);
    try {
      await api.undoLatestEdit(selectedTrip.id);
      await loadReconstruction(selectedTrip.id);
    } catch (error) {
      setReconstructionError(messageFrom(error));
    } finally {
      setIsBusy(false);
    }
  }

  async function renameStop(stopId: string, title: string) {
    if (!selectedTrip) {
      return;
    }
    const previousReconstruction = reconstruction;
    const previousStoryProjection = storyProjection;
    setReconstructionError("");
    setReconstruction((current) =>
      renameStopInReconstruction(current, stopId, title),
    );
    setStoryProjection((current) =>
      renameStopInReconstruction(current, stopId, title),
    );
    try {
      await api.createEditOperation(selectedTrip.id, {
        operationType: "rename_stop",
        payload: { stopId, title },
      });
      await loadReconstruction(selectedTrip.id);
    } catch (error) {
      setReconstruction(previousReconstruction);
      setStoryProjection(previousStoryProjection);
      setReconstructionError(messageFrom(error));
      throw error;
    }
  }

  async function setDayNote(dayId: string, note: string) {
    if (!selectedTrip) {
      return;
    }
    setReconstructionError("");
    try {
      await api.createEditOperation(selectedTrip.id, {
        operationType: "set_day_note",
        payload: { dayId, note },
      });
      await loadReconstruction(selectedTrip.id);
    } catch (error) {
      setReconstructionError(messageFrom(error));
      throw error;
    }
  }

  async function setStopNote(stopId: string, note: string) {
    if (!selectedTrip) {
      return;
    }
    setReconstructionError("");
    try {
      await api.createEditOperation(selectedTrip.id, {
        operationType: "set_stop_note",
        payload: { stopId, note },
      });
      await loadReconstruction(selectedTrip.id);
    } catch (error) {
      setReconstructionError(messageFrom(error));
      throw error;
    }
  }

  async function mergeStops(sourceStopId: string, targetStopId: string) {
    if (!selectedTrip) {
      return;
    }
    setReconstructionError("");
    try {
      await api.createEditOperation(selectedTrip.id, {
        operationType: "merge_stops",
        payload: { sourceStopId, targetStopId },
      });
      await loadReconstruction(selectedTrip.id);
    } catch (error) {
      setReconstructionError(messageFrom(error));
      throw error;
    }
  }

  async function splitStop(stopId: string, afterMediaItemId: string) {
    if (!selectedTrip) {
      return;
    }
    setReconstructionError("");
    try {
      await api.createEditOperation(selectedTrip.id, {
        operationType: "split_stop",
        payload: { stopId, afterMediaItemId },
      });
      await loadReconstruction(selectedTrip.id);
    } catch (error) {
      setReconstructionError(messageFrom(error));
      throw error;
    }
  }

  async function renameAreaVisit(areaVisitId: string, title: string) {
    if (!selectedTrip) {
      return;
    }
    setReconstructionError("");
    try {
      await api.createEditOperation(selectedTrip.id, {
        operationType: "rename_area_visit",
        payload: { areaVisitId, title },
      });
      await loadReconstruction(selectedTrip.id);
    } catch (error) {
      setReconstructionError(messageFrom(error));
      throw error;
    }
  }

  async function createAreaVisit(
    dayId: string,
    stopIds: string[],
    title: string,
  ) {
    if (!selectedTrip) {
      return;
    }
    setReconstructionError("");
    try {
      await api.createEditOperation(selectedTrip.id, {
        operationType: "create_area_visit",
        payload: { dayId, stopIds, title },
      });
      await loadReconstruction(selectedTrip.id);
    } catch (error) {
      setReconstructionError(messageFrom(error));
      throw error;
    }
  }

  async function addAreaVisitStop(areaVisitId: string, stopId: string) {
    if (!selectedTrip) {
      return;
    }
    setReconstructionError("");
    try {
      await api.createEditOperation(selectedTrip.id, {
        operationType: "add_area_visit_stop",
        payload: { areaVisitId, stopId },
      });
      await loadReconstruction(selectedTrip.id);
    } catch (error) {
      setReconstructionError(messageFrom(error));
      throw error;
    }
  }

  async function removeAreaVisitStop(areaVisitId: string, stopId: string) {
    if (!selectedTrip) {
      return;
    }
    setReconstructionError("");
    try {
      await api.createEditOperation(selectedTrip.id, {
        operationType: "remove_area_visit_stop",
        payload: { areaVisitId, stopId },
      });
      await loadReconstruction(selectedTrip.id);
    } catch (error) {
      setReconstructionError(messageFrom(error));
      throw error;
    }
  }

  async function deleteAreaVisit(areaVisitId: string) {
    if (!selectedTrip) {
      return;
    }
    setReconstructionError("");
    try {
      await api.createEditOperation(selectedTrip.id, {
        operationType: "delete_area_visit",
        payload: { areaVisitId },
      });
      await loadReconstruction(selectedTrip.id);
    } catch (error) {
      setReconstructionError(messageFrom(error));
      throw error;
    }
  }

  async function publishTrip() {
    if (!selectedTrip) {
      return;
    }
    setPublicationError("");
    setIsBusy(true);
    try {
      const result = await api.publishTrip(selectedTrip.id);
      setLatestShareUrl(result.shareLink.shareUrl ?? "");
      await loadPublications(selectedTrip.id);
    } catch (error) {
      setPublicationError(messageFrom(error));
    } finally {
      setIsBusy(false);
    }
  }

  async function revokeShareLink(id: string) {
    if (!selectedTrip) {
      return;
    }
    setPublicationError("");
    try {
      await api.revokeShareLink(id);
      await loadPublications(selectedTrip.id);
    } catch (error) {
      setPublicationError(messageFrom(error));
    }
  }

  async function unpublishTrip() {
    if (!selectedTrip) {
      return;
    }
    setPublicationError("");
    setIsBusy(true);
    try {
      await api.unpublishTrip(selectedTrip.id);
      setLatestShareUrl("");
      await loadPublications(selectedTrip.id);
    } catch (error) {
      setPublicationError(messageFrom(error));
    } finally {
      setIsBusy(false);
    }
  }

  if (loadState === "loading") {
    return (
      <main className="app-shell">
        <p className="eyebrow">TripWeave</p>
        <h1>Loading workspace</h1>
      </main>
    );
  }

  if (!user) {
    return (
      <main className="auth-shell">
        <section className="auth-panel" aria-labelledby="auth-title">
          <p className="eyebrow">TripWeave</p>
          <h1 id="auth-title">
            {mode === "register" ? "Create owner account" : "Sign in"}
          </h1>
          <form className="stack" onSubmit={submitAuth}>
            {mode === "register" ? (
              <label>
                Display name
                <input
                  autoComplete="name"
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  required
                />
              </label>
            ) : null}
            <label>
              Email
              <input
                autoComplete="email"
                inputMode="email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </label>
            <label>
              Password
              <input
                autoComplete={
                  mode === "register" ? "new-password" : "current-password"
                }
                minLength={8}
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </label>
            {authError ? <p className="error">{authError}</p> : null}
            <button type="submit" disabled={isBusy}>
              {isBusy
                ? "Working..."
                : mode === "register"
                  ? "Register"
                  : "Sign in"}
            </button>
          </form>
          <button
            className="link-button"
            type="button"
            onClick={() => {
              setAuthError("");
              setMode(mode === "register" ? "login" : "register");
            }}
          >
            {mode === "register"
              ? "Already have an account?"
              : "Create an owner account"}
          </button>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell owner-workspace-shell">
      <header className="app-header workspace-header">
        <div>
          <strong>TripWeave</strong>
          <span>{user.display_name}</span>
        </div>
        <button type="button" onClick={logout} disabled={isBusy}>
          Logout
        </button>
      </header>

      {tripError ? <p className="error">{tripError}</p> : null}

      <nav className="mobile-trip-actions" aria-label="Trip sections">
        {(
          [
            ["story", "Map", "story"],
            ["timeline", "Timeline", "timeline"],
          ] as Array<[MobileWorkspaceTab, string, StoryHeaderIconAction]>
        ).map(([tab, label, icon]) => (
          <button
            type="button"
            aria-label={label}
            aria-pressed={mobileTab === tab}
            className={mobileTab === tab ? "active" : ""}
            disabled={!selectedTrip}
            key={tab}
            onClick={() => {
              setOwnerStoryPhotosOpen(false);
              setMobileTripMenuOpen(false);
              setMobileTab(tab);
            }}
            title={label}
          >
            <StoryHeaderIcon action={icon} />
          </button>
        ))}
        <button
          type="button"
          aria-label="Play slideshow"
          disabled={!canOpenOwnerSlideshow}
          onClick={() => {
            setOwnerStoryPhotosOpen(false);
            setMobileTripMenuOpen(false);
            setOwnerSlideshowOpen(true);
          }}
          title="Play slideshow"
        >
          <StoryHeaderIcon action="slideshow" />
        </button>
        {canManageSelectedTrip ? (
          <button
            type="button"
            aria-label="Trip actions"
            aria-expanded={mobileTripMenuOpen}
            className={mobileTripMenuOpen ? "active" : ""}
            disabled={!selectedTrip}
            onClick={() => setMobileTripMenuOpen((current) => !current)}
            title="Trip actions"
          >
            <StoryHeaderIcon action="more" />
          </button>
        ) : (
          <button
            type="button"
            aria-label="Upload photos"
            aria-pressed={mobileTab === "photos"}
            className={mobileTab === "photos" ? "active" : ""}
            disabled={!selectedTrip}
            onClick={() => {
              setOwnerStoryPhotosOpen(false);
              setMobileTripMenuOpen(false);
              setMobileTab("photos");
            }}
            title="Upload photos"
          >
            <StoryHeaderIcon action="upload" />
          </button>
        )}
        <button
          type="button"
          aria-label="Settings"
          aria-pressed={mobileTab === "appSettings"}
          className={mobileTab === "appSettings" ? "active" : ""}
          onClick={() => {
            setOwnerStoryPhotosOpen(false);
            setMobileTripMenuOpen(false);
            setMobileTab("appSettings");
          }}
          title="Settings"
        >
          <StoryHeaderIcon action="settings" />
        </button>
      </nav>
      {mobileTripMenuOpen && canManageSelectedTrip ? (
        <nav className="mobile-trip-action-menu" aria-label="Trip actions">
          <button
            type="button"
            aria-label={
              isReconstructingStory ? "Updating story" : "Update story"
            }
            className={
              isReconstructingStory
                ? "is-updating"
                : storyUpdateNeeded
                  ? "needs-update"
                  : ""
            }
            disabled={isStoryActionDisabled}
            aria-busy={isReconstructingStory}
            onClick={() => {
              setOwnerStoryPhotosOpen(false);
              setMobileTripMenuOpen(false);
              void runReconstruction();
            }}
            title={storyActionTitle}
          >
            {isReconstructingStory ? (
              <span className="button-spinner" aria-hidden="true" />
            ) : (
              <StoryHeaderIcon action="update" />
            )}
          </button>
          <button
            type="button"
            aria-label="Upload photos"
            aria-pressed={mobileTab === "photos"}
            className={mobileTab === "photos" ? "active" : ""}
            onClick={() => {
              setOwnerStoryPhotosOpen(false);
              setMobileTripMenuOpen(false);
              setMobileTab("photos");
            }}
            title="Upload photos"
          >
            <StoryHeaderIcon action="upload" />
          </button>
          <button
            type="button"
            aria-label="Share trip"
            aria-pressed={mobileTab === "share"}
            className={mobileTab === "share" ? "active" : ""}
            disabled={!["owner", "editor"].includes(selectedTrip?.role ?? "")}
            onClick={() => {
              setOwnerStoryPhotosOpen(false);
              setMobileTripMenuOpen(false);
              setMobileTab("share");
            }}
            title="Share trip"
          >
            <StoryHeaderIcon action="share" />
          </button>
          <button
            type="button"
            aria-label="Trip settings"
            aria-pressed={mobileTab === "tripSettings"}
            className={mobileTab === "tripSettings" ? "active" : ""}
            disabled={!["owner", "editor"].includes(selectedTrip?.role ?? "")}
            onClick={() => {
              setOwnerStoryPhotosOpen(false);
              setMobileTripMenuOpen(false);
              setMobileTab("tripSettings");
            }}
            title="Trip settings"
          >
            <StoryHeaderIcon action="manage" />
          </button>
        </nav>
      ) : null}

      <section className="workspace trip-workspace">
        <aside
          className={`trip-nav panel ${
            mobileTab === "appSettings" ? "mobile-tab-active" : ""
          }`}
          aria-label="Trip navigation"
          data-mobile-tab-panel="appSettings"
        >
          <div className="trip-brand">
            <strong>My Trip</strong>
            <span>{user.display_name}</span>
          </div>
          <div className="mobile-account-card">
            <div>
              <span>Signed in</span>
              <strong>{user.display_name}</strong>
            </div>
            <button type="button" onClick={logout} disabled={isBusy}>
              Logout
            </button>
          </div>
          {selectedTrip && ["owner", "editor"].includes(selectedTrip.role) ? (
            <div className="mobile-story-actions">
              <button
                className={storyUpdateNeeded ? "needs-update" : undefined}
                type="button"
                onClick={runReconstruction}
                disabled={isStoryActionDisabled}
                aria-busy={isReconstructingStory}
                title={storyActionTitle}
              >
                {isReconstructingStory ? (
                  <span className="button-spinner" aria-hidden="true" />
                ) : null}
                {storyActionButtonLabel}
              </button>
              {storyUpdate || isReconstructingStory ? (
                <span
                  className={
                    isReconstructingStory
                      ? "story-update-status updating"
                      : storyUpdateNeeded
                        ? "story-update-status needs-update"
                        : "story-update-status"
                  }
                >
                  {storyActionStatusLabel}
                </span>
              ) : null}
            </div>
          ) : null}
          <nav className="trip-primary-nav" aria-label="Workspace sections">
            <a href="#trip-stage-title" className="active">
              Story
            </a>
            <a href="#photos-panel">Photos</a>
            {selectedTrip?.role === "owner" ? (
              <a href="#travelers-panel">Travelers</a>
            ) : null}
            {selectedTrip && ["owner", "editor"].includes(selectedTrip.role) ? (
              <>
                <a href="#review-panel">Review</a>
                <a href="#publish-panel">Publish</a>
              </>
            ) : null}
            <a href="#settings-panel">Settings</a>
          </nav>
          <section aria-labelledby="trip-list-title">
            <div className="nav-section-heading">
              <h2 id="trip-list-title">Trips</h2>
              <span>
                {trips.length} trip{trips.length === 1 ? "" : "s"}
              </span>
            </div>
            {trips.length === 0 ? (
              <p>No trips yet.</p>
            ) : (
              <div className="trip-list" role="list">
                {trips.map((trip) => (
                  <button
                    className={
                      trip.id === selectedTrip?.id
                        ? "trip-row trip-row-active"
                        : "trip-row"
                    }
                    key={trip.id}
                    type="button"
                    onClick={() => selectTrip(trip)}
                  >
                    <span>{trip.title}</span>
                    <small>{trip.role}</small>
                  </button>
                ))}
              </div>
            )}
          </section>
          <details className="management-panel">
            <summary>Create trip</summary>
            <form className="stack" onSubmit={createTrip}>
              <TripFields form={createForm} onChange={setCreateForm} />
              <button type="submit" disabled={isBusy}>
                Create trip
              </button>
            </form>
          </details>
        </aside>

        <section
          className={`trip-stage ${
            ["story", "timeline"].includes(mobileTab) ? "mobile-tab-active" : ""
          }`}
          aria-labelledby="trip-stage-title"
          data-mobile-tab-panel="story"
        >
          {selectedTrip ? (
            <>
              <div className="trip-stage-header">
                <div>
                  <h2 id="trip-stage-title">{selectedTrip.title}</h2>
                  <p>
                    {selectedTrip.startDate} - {selectedTrip.endDate}
                  </p>
                </div>
                {storyForExplorer?.latestRun || canOrganizeSelectedTrip ? (
                  <div className="trip-stage-header-actions">
                    <button
                      className="story-photo-icon-button desktop-story-photo-button"
                      type="button"
                      aria-label="Browse selected day photos"
                      title="Browse selected day photos"
                      onClick={() => void openOwnerStoryPhotos()}
                      disabled={!storyForExplorer?.latestRun}
                    >
                      <StoryHeaderIcon action="photos" />
                    </button>
                    <button
                      className="story-photo-icon-button desktop-story-photo-button"
                      type="button"
                      aria-label="Play slideshow"
                      title="Play slideshow"
                      onClick={() => setOwnerSlideshowOpen(true)}
                      disabled={!canOpenOwnerSlideshow}
                    >
                      <StoryHeaderIcon action="slideshow" />
                    </button>
                    {canOrganizeSelectedTrip ? (
                      <div className="button-row">
                        <div className="story-action-stack">
                          <button
                            className={
                              isReconstructingStory
                                ? "is-updating"
                                : storyUpdateNeeded
                                  ? "needs-update"
                                  : undefined
                            }
                            type="button"
                            onClick={runReconstruction}
                            disabled={isStoryActionDisabled}
                            aria-busy={isReconstructingStory}
                            title={storyActionTitle}
                          >
                            {isReconstructingStory ? (
                              <span
                                className="button-spinner"
                                aria-hidden="true"
                              />
                            ) : null}
                            {storyActionButtonLabel}
                          </button>
                          {storyUpdate || isReconstructingStory ? (
                            <span
                              className={
                                isReconstructingStory
                                  ? "story-update-status updating"
                                  : storyUpdateNeeded
                                    ? "story-update-status needs-update"
                                    : "story-update-status"
                              }
                            >
                              {storyActionStatusLabel}
                            </span>
                          ) : null}
                        </div>
                        <button
                          type="button"
                          onClick={publishTrip}
                          disabled={isBusy}
                        >
                          Publish
                        </button>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
              {reconstructionError ? (
                <p className="error">{reconstructionError}</p>
              ) : null}
              {selectedTrip ? (
                <TripStoryExplorer
                  reconstruction={storyForExplorer}
                  tripId={selectedTrip.id}
                  isLoading={isStoryExplorerLoading}
                  state={storyState}
                  onStateChange={setStoryState}
                  onMergeStops={
                    canOrganizeSelectedTrip ? mergeStops : undefined
                  }
                  onCreateAreaVisit={
                    canOrganizeSelectedTrip ? createAreaVisit : undefined
                  }
                  onAddAreaVisitStop={
                    canOrganizeSelectedTrip ? addAreaVisitStop : undefined
                  }
                  onRemoveAreaVisitStop={
                    canOrganizeSelectedTrip ? removeAreaVisitStop : undefined
                  }
                  onDeleteAreaVisit={
                    canOrganizeSelectedTrip ? deleteAreaVisit : undefined
                  }
                  onRenameAreaVisit={
                    canOrganizeSelectedTrip ? renameAreaVisit : undefined
                  }
                  onRenameStop={
                    canOrganizeSelectedTrip ? renameStop : undefined
                  }
                  onSetDayNote={
                    canOrganizeSelectedTrip ? setDayNote : undefined
                  }
                  onSetStopNote={
                    canOrganizeSelectedTrip ? setStopNote : undefined
                  }
                  onSplitStop={canOrganizeSelectedTrip ? splitStop : undefined}
                  mobilePane={
                    ownerStoryPhotosOpen
                      ? "photos"
                      : mobileTab === "timeline"
                        ? "timeline"
                        : "map"
                  }
                  onMobilePaneChange={(pane) => {
                    if (pane === "photos") {
                      openOwnerStoryPhotos();
                    } else {
                      setOwnerStoryPhotosOpen(false);
                    }
                    if (pane === "map") {
                      setMobileTab("story");
                    } else if (pane === "timeline") {
                      setMobileTab("timeline");
                    }
                  }}
                  onOpenPhotos={openOwnerStoryPhotos}
                  timezoneId={selectedTrip.timezoneId}
                />
              ) : null}
              {ownerSlideshowOpen && selectedTrip ? (
                <PublicStorySlideshow
                  scenes={ownerSlideshowScenes}
                  title={selectedTrip.title}
                  timezoneId={selectedTrip.timezoneId}
                  onExit={() => setOwnerSlideshowOpen(false)}
                />
              ) : null}
            </>
          ) : (
            <div className="story-empty trip-start">
              <p className="eyebrow">Start here</p>
              <h2 id="trip-stage-title">Choose or create a trip</h2>
              <p>
                TripWeave turns shared photos into a map and timeline once a
                trip has photos.
              </p>
            </div>
          )}
        </section>

        <aside className="trip-management" aria-label="Trip management">
          <details
            className={`management-panel ${
              mobileTab === "photos" ? "mobile-tab-active" : ""
            }`}
            id="photos-panel"
            open={isMobileWorkspace ? mobileTab === "photos" : true}
            data-mobile-tab-panel="photos"
          >
            <summary>
              <span>Photos</span>
              {selectedTrip ? (
                <small>
                  {media.length} photo{media.length === 1 ? "" : "s"}
                </small>
              ) : null}
            </summary>
            {selectedTrip ? (
              <div className="stack">
                <div
                  className="drop-zone"
                  onDragOver={(event) => event.preventDefault()}
                  onDrop={onDrop}
                >
                  <label>
                    Add photos
                    <input
                      accept=".jpg,.jpeg,.heic,image/jpeg,image/heic,image/heif"
                      multiple
                      type="file"
                      onChange={onFileInput}
                    />
                  </label>
                  <p>JPEG and HEIC</p>
                </div>
                {uploadError ? <p className="error">{uploadError}</p> : null}
                <StoryAutoUpdateNotice
                  canUpdateStory={canOrganizeSelectedTrip}
                  hasProcessingMedia={hasProcessingMedia}
                  hasStory={Boolean(storyForExplorer?.latestRun)}
                  isUpdating={isReconstructingStory}
                  storyUpdate={storyUpdate}
                />
                <UploadFileList
                  files={selectedUploadFiles}
                  progress={uploadProgress}
                  onCancel={cancelUpload}
                  onRetry={retryUpload}
                />
                <div className="panel-heading">
                  <h2 id="media-title">Photo library</h2>
                  <span>{hasProcessingMedia ? "Preparing" : "Ready"}</span>
                </div>
                {mediaError ? <p className="error">{mediaError}</p> : null}
                <MediaList
                  media={media}
                  onRetry={canOrganizeSelectedTrip ? retryMedia : undefined}
                  onVisibilityChange={updateMediaVisibility}
                  canChangeVisibility={(item) =>
                    Boolean(item.canUpdateVisibility) ||
                    item.contributorMemberId === selectedTrip?.memberId
                  }
                  timezoneId={selectedTrip?.timezoneId}
                />
                {canOrganizeSelectedTrip ? (
                  <SimilarityGroupsPanel
                    groups={similarityGroups}
                    onChangeRepresentative={(groupId, mediaId) =>
                      void changeSimilarityRepresentative(groupId, mediaId)
                    }
                  />
                ) : null}
              </div>
            ) : (
              <p>Select a trip before uploading photos.</p>
            )}
          </details>

          {selectedTrip?.role === "owner" ? (
            <details
              className={`management-panel ${
                mobileTab === "tripSettings" ? "mobile-tab-active" : ""
              }`}
              id="travelers-panel"
              open={
                isMobileWorkspace ? mobileTab === "tripSettings" : undefined
              }
              data-mobile-tab-panel="tripSettings"
            >
              <summary>
                <span>Travelers</span>
                <small>
                  {activeMemberCount} member
                  {activeMemberCount === 1 ? "" : "s"}
                </small>
              </summary>
              <div className="stack">
                {collaborationError ? (
                  <p className="error">{collaborationError}</p>
                ) : null}
                <div className="action-row">
                  <button
                    type="button"
                    onClick={createInvite}
                    disabled={isBusy}
                  >
                    Create invite link
                  </button>
                  {latestInviteUrl ? (
                    <button type="button" onClick={copyInviteUrl}>
                      Copy link
                    </button>
                  ) : null}
                </div>
                {latestInviteUrl ? (
                  <div className="invite-card">
                    <code>{latestInviteUrl}</code>
                    {latestInviteQrUrl ? (
                      <img
                        className="qr-block"
                        src={latestInviteQrUrl}
                        alt="Invitation QR code"
                      />
                    ) : null}
                  </div>
                ) : null}
                <InvitationList
                  invitations={invitations}
                  onRevoke={revokeInvite}
                />
                <MemberRoster members={members} onRemove={removeMember} />
              </div>
            </details>
          ) : null}

          {selectedTrip && ["owner", "editor"].includes(selectedTrip.role) ? (
            <details
              className={`management-panel ${
                mobileTab === "tripSettings" ? "mobile-tab-active" : ""
              }`}
              id="review-panel"
              open={
                isMobileWorkspace ? mobileTab === "tripSettings" : undefined
              }
              data-mobile-tab-panel="tripSettings"
              onToggle={(event) => {
                if (event.currentTarget.open) {
                  loadReviewDetails();
                }
              }}
            >
              <summary>
                <span>Review</span>
                <small>
                  {openReviewCount} issue{openReviewCount === 1 ? "" : "s"}
                </small>
              </summary>
              <div className="stack">
                <ReconstructionOutline
                  reconstruction={reconstruction}
                  timezoneId={selectedTrip.timezoneId}
                  reviewIndex={reviewIndex}
                  onSkipReview={() => setReviewIndex((current) => current + 1)}
                  onResolveReview={(id) =>
                    void applyReviewDecision(id, "resolve_review_item")
                  }
                  onDismissReview={(id) =>
                    void applyReviewDecision(id, "dismiss_review_item")
                  }
                  onAcceptClockOffset={(id) => void acceptClockOffset(id)}
                  onUndo={undoLatestEdit}
                />
              </div>
            </details>
          ) : null}

          {selectedTrip && ["owner", "editor"].includes(selectedTrip.role) ? (
            <details
              className={`management-panel ${
                mobileTab === "share" ? "mobile-tab-active" : ""
              }`}
              id="publish-panel"
              open={isMobileWorkspace ? mobileTab === "share" : undefined}
              data-mobile-tab-panel="share"
            >
              <summary>
                <span>Publish</span>
                <small>
                  {activeShareCount} active link
                  {activeShareCount === 1 ? "" : "s"}
                </small>
              </summary>
              <div className="stack">
                <div className="button-row">
                  <button type="button" onClick={publishTrip} disabled={isBusy}>
                    Publish
                  </button>
                  <button
                    className="danger"
                    type="button"
                    onClick={unpublishTrip}
                    disabled={isBusy}
                  >
                    Unpublish
                  </button>
                </div>
                {publicationError ? (
                  <p className="error">{publicationError}</p>
                ) : null}
                {latestShareUrl ? (
                  <div className="invite-card">
                    <code>{latestShareUrl}</code>
                    <button type="button" onClick={copyLatestShareUrl}>
                      Copy link
                    </button>
                  </div>
                ) : null}
                <PublicationList
                  publications={publications}
                  onRevoke={revokeShareLink}
                />
              </div>
            </details>
          ) : null}

          <details
            className={`management-panel ${
              mobileTab === "tripSettings" ? "mobile-tab-active" : ""
            }`}
            id="settings-panel"
            open={isMobileWorkspace ? mobileTab === "tripSettings" : undefined}
            data-mobile-tab-panel="tripSettings"
          >
            <summary>
              <span>Trip info</span>
              {selectedTrip ? <small>{selectedTrip.timezoneId}</small> : null}
            </summary>
            <form className="stack" onSubmit={updateTrip}>
              {selectedTrip ? (
                <>
                  <TripFields form={settingsForm} onChange={setSettingsForm} />
                  <div className="button-row">
                    <button type="submit" disabled={isBusy}>
                      Save changes
                    </button>
                    <button
                      className="danger"
                      type="button"
                      onClick={deleteTrip}
                      disabled={isBusy}
                    >
                      Delete trip
                    </button>
                  </div>
                </>
              ) : (
                <p>Select a trip to edit its settings.</p>
              )}
            </form>
          </details>
        </aside>
      </section>
    </main>
  );
}

function InviteAcceptance({ token }: { token: string }) {
  const [preview, setPreview] = useState<InvitationPreviewResponse | null>(
    null,
  );
  const [user, setUser] = useState<UserResponse | null>(null);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .previewInvitation(token)
      .then((result) => {
        if (!cancelled) {
          setPreview(result);
        }
      })
      .catch((reason) => {
        if (!cancelled) {
          setError(messageFrom(reason));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    let cancelled = false;
    api
      .me()
      .then((result) => {
        if (!cancelled) {
          setUser(result.user);
          setDisplayName(result.user.display_name);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setUser(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function joinTrip() {
    const member = await api.acceptInvitation(token, {});
    window.location.assign(`/?tripId=${encodeURIComponent(member.tripId)}`);
  }

  async function authenticateAndAccept(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result =
        authMode === "register"
          ? await api.register({ email, password, displayName })
          : await api.login({ email, password });
      setUser(result.user);
      const member = await api.acceptInvitation(token, {
        displayName:
          authMode === "register" && displayName.trim()
            ? displayName.trim()
            : result.user.display_name,
      });
      window.location.assign(`/?tripId=${encodeURIComponent(member.tripId)}`);
    } catch (reason) {
      setError(messageFrom(reason));
    } finally {
      setBusy(false);
    }
  }

  async function acceptExistingSession() {
    setBusy(true);
    setError("");
    try {
      await joinTrip();
    } catch (reason) {
      setError(messageFrom(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-panel stack" aria-labelledby="invite-title">
        <p className="eyebrow">TripWeave invitation</p>
        <h1 id="invite-title">
          {preview ? preview.title : "Loading invitation"}
        </h1>
        {preview ? (
          <p>
            Sign in or create an account to join this trip as a {preview.role}.
          </p>
        ) : null}
        {user ? (
          <div className="stack">
            <p>Signed in as {user.display_name}.</p>
            {error ? <p className="error">{error}</p> : null}
            <button
              type="button"
              onClick={acceptExistingSession}
              disabled={busy || !preview}
            >
              Join trip
            </button>
          </div>
        ) : (
          <form className="stack" onSubmit={authenticateAndAccept}>
            <div
              className="auth-toggle"
              role="tablist"
              aria-label="Invitation account mode"
            >
              <button
                type="button"
                className={authMode === "login" ? "active" : ""}
                onClick={() => setAuthMode("login")}
              >
                Log in
              </button>
              <button
                type="button"
                className={authMode === "register" ? "active" : ""}
                onClick={() => setAuthMode("register")}
              >
                Create account
              </button>
            </div>
            <label>
              Email
              <input
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                type="email"
                required
                maxLength={320}
              />
            </label>
            <label>
              Password
              <input
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                type="password"
                required
                minLength={authMode === "register" ? 8 : 1}
                maxLength={256}
              />
            </label>
            {authMode === "register" ? (
              <label>
                Display name
                <input
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  required
                  maxLength={160}
                />
              </label>
            ) : null}
            {error ? <p className="error">{error}</p> : null}
            <button type="submit" disabled={busy || !preview}>
              {authMode === "register"
                ? "Create account and join"
                : "Log in and join"}
            </button>
          </form>
        )}
      </section>
    </main>
  );
}

function ContributorWorkspace({ tripId }: { tripId: string }) {
  const [guest, setGuest] = useState<GuestMemberResponse | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [uploadSessions, setUploadSessions] = useState<UploadSessionResponse[]>(
    [],
  );
  const [media, setMedia] = useState<MediaItemResponse[]>([]);
  const [uploadProgress, setUploadProgress] = useState<
    Record<string, UploadProgress>
  >({});
  const [error, setError] = useState("");
  const localFiles = useRef<Map<string, File>>(new Map());
  const abortUpload = useRef<Map<string, () => void>>(new Map());

  const selectedUploadFiles = useMemo(
    () => uploadSessions.flatMap((session) => session.files),
    [uploadSessions],
  );
  const hasProcessingMedia = useMemo(
    () =>
      media.some((item) =>
        ["pending", "processing"].includes(item.processingState),
      ),
    [media],
  );

  const loadContribution = useCallback(async () => {
    const [sessionResult, mediaResult] = await Promise.all([
      guestApi.uploadSessions(tripId),
      guestApi.media(tripId),
    ]);
    setUploadSessions(sessionResult.uploadSessions);
    setMedia(mediaResult.media);
  }, [tripId]);

  useEffect(() => {
    let cancelled = false;
    async function loadGuest() {
      try {
        const result = await guestApi.guestMe();
        if (!cancelled) {
          setGuest(result);
          await loadContribution();
        }
      } catch (reason) {
        if (!cancelled) {
          setError(messageFrom(reason));
        }
      } finally {
        if (!cancelled) {
          setLoadState("ready");
        }
      }
    }
    void loadGuest();
    return () => {
      cancelled = true;
    };
  }, [loadContribution]);

  useEffect(() => {
    if (!hasProcessingMedia) {
      return;
    }
    let cancelled = false;
    let delay = 1200;
    let timeout: ReturnType<typeof setTimeout> | null = null;
    async function poll() {
      try {
        const result = await guestApi.media(tripId);
        if (cancelled) {
          return;
        }
        setMedia(result.media);
        if (
          result.media.some((item) =>
            ["pending", "processing"].includes(item.processingState),
          )
        ) {
          timeout = setTimeout(poll, delay);
          delay = Math.min(delay * 1.6, 10000);
        }
      } catch {
        timeout = setTimeout(poll, delay);
      }
    }
    void poll();
    return () => {
      cancelled = true;
      if (timeout) {
        clearTimeout(timeout);
      }
    };
  }, [hasProcessingMedia, tripId]);

  function rememberProgress(fileId: string, next: UploadProgress) {
    setUploadProgress((current) => ({ ...current, [fileId]: next }));
  }

  async function uploadOne(uploadFile: UploadFileResponse, file: File) {
    if (!uploadFile.grant) {
      rememberProgress(uploadFile.id, {
        loaded: 0,
        total: file.size,
        status: "failed",
        error: "Upload grant is unavailable",
      });
      return;
    }
    rememberProgress(uploadFile.id, {
      loaded: 0,
      total: file.size,
      status: "uploading",
    });
    const transfer = uploadWithProgress({
      url: uploadFile.grant.url,
      file,
      headers: stringHeaders(uploadFile.grant.headers),
      onProgress: (loaded, total) =>
        rememberProgress(uploadFile.id, { loaded, total, status: "uploading" }),
    });
    abortUpload.current.set(uploadFile.id, transfer.abort);
    try {
      await transfer.promise;
      await guestApi.completeUploadFile(uploadFile.id);
      rememberProgress(uploadFile.id, {
        loaded: file.size,
        total: file.size,
        status: "complete",
      });
    } catch (reason) {
      rememberProgress(uploadFile.id, {
        loaded: 0,
        total: file.size,
        status: "failed",
        error: messageFrom(reason),
      });
    } finally {
      abortUpload.current.delete(uploadFile.id);
    }
  }

  async function uploadFiles(files: File[]) {
    if (files.length === 0) {
      return;
    }
    setError("");
    try {
      const session = await guestApi.createUploadSession(tripId, {
        files: files.map((file) => ({
          filename: file.name,
          byteSize: file.size,
          mimeType: uploadMimeType(file),
        })),
      });
      setUploadSessions((current) => [session, ...current]);
      session.files.forEach((uploadFile, index) => {
        const file = files[index];
        if (file) {
          localFiles.current.set(uploadFile.id, file);
          rememberProgress(uploadFile.id, {
            loaded: 0,
            total: file.size,
            status: "pending",
          });
        }
      });
      for (const uploadFile of session.files) {
        const file = localFiles.current.get(uploadFile.id);
        if (file) {
          await uploadOne(uploadFile, file);
        }
      }
      await loadContribution();
    } catch (reason) {
      setError(messageFrom(reason));
    }
  }

  async function cancelUpload(uploadFile: UploadFileResponse) {
    abortUpload.current.get(uploadFile.id)?.();
    rememberProgress(uploadFile.id, {
      loaded: 0,
      total: uploadFile.byteSize ?? 0,
      status: "cancelled",
    });
    await guestApi.cancelUploadFile(uploadFile.id);
    await loadContribution();
  }

  async function retryUpload(
    uploadFile: UploadFileResponse,
    selectedFile?: File,
  ) {
    const file = selectedFile ?? localFiles.current.get(uploadFile.id);
    if (!file) {
      return;
    }
    localFiles.current.set(uploadFile.id, file);
    await uploadOne(uploadFile, file);
    await loadContribution();
  }

  async function updateOwnMedia(item: MediaItemResponse, visibility: string) {
    await guestApi.updateMedia(item.id, {
      visibility,
      includeInStory: visibility === "story",
    });
    await loadContribution();
  }

  async function deleteOwnMedia(item: MediaItemResponse) {
    await guestApi.updateMedia(item.id, { deleted: true });
    await loadContribution();
  }

  if (loadState === "loading") {
    return (
      <main className="app-shell">
        <h1>Loading contribution page</h1>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <section className="panel stack">
        <p className="eyebrow">Contributor upload</p>
        <h1>
          {guest ? `Welcome, ${guest.displayName}` : "Contribution unavailable"}
        </h1>
        {error ? <p className="error">{error}</p> : null}
        {guest ? (
          <>
            <div
              className="drop-zone"
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                void uploadFiles(Array.from(event.dataTransfer.files));
              }}
            >
              <label>
                Add JPEG or HEIC images
                <input
                  accept=".jpg,.jpeg,.heic,image/jpeg,image/heic,image/heif"
                  multiple
                  type="file"
                  onChange={(event) =>
                    void uploadFiles(Array.from(event.target.files ?? []))
                  }
                />
              </label>
              <p>Only your uploads are shown here.</p>
            </div>
            <UploadFileList
              files={selectedUploadFiles}
              progress={uploadProgress}
              onCancel={cancelUpload}
              onRetry={retryUpload}
            />
            <MediaList
              media={media}
              onRetry={async (item) => {
                await guestApi.retryMedia(item.id);
                await loadContribution();
              }}
              onVisibilityChange={updateOwnMedia}
              canChangeVisibility={(item) =>
                Boolean(item.canUpdateVisibility) ||
                item.contributorMemberId === guest?.id
              }
              onDelete={deleteOwnMedia}
            />
          </>
        ) : null}
      </section>
    </main>
  );
}

type LocalGridFeature = {
  type: "Feature";
  properties: { axis: "longitude" | "latitude" };
  geometry: { type: "LineString"; coordinates: number[][] };
};

function localGridData() {
  const features: LocalGridFeature[] = [];
  for (let longitude = -180; longitude <= 180; longitude += 30) {
    features.push({
      type: "Feature" as const,
      properties: { axis: "longitude" },
      geometry: {
        type: "LineString" as const,
        coordinates: [
          [longitude, -85],
          [longitude, 85],
        ],
      },
    });
  }
  for (let latitude = -80; latitude <= 80; latitude += 20) {
    features.push({
      type: "Feature" as const,
      properties: { axis: "latitude" },
      geometry: {
        type: "LineString" as const,
        coordinates: [
          [-180, latitude],
          [180, latitude],
        ],
      },
    });
  }
  return {
    type: "FeatureCollection" as const,
    features,
  };
}

const localMapStyle: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    "local-grid": {
      type: "geojson",
      data: localGridData(),
    },
  },
  layers: [
    {
      id: "local-background",
      type: "background",
      paint: { "background-color": "#e7efe9" },
    },
    {
      id: "local-grid-lines",
      type: "line",
      source: "local-grid",
      paint: {
        "line-color": "#c2d0c9",
        "line-opacity": 0.7,
        "line-width": 0.8,
      },
    },
  ],
};

function configuredMapStyle(): string | maplibregl.StyleSpecification {
  return process.env.NEXT_PUBLIC_TRIPWEAVE_MAP_STYLE_URL || localMapStyle;
}

function hasConfiguredMapStyle(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_TRIPWEAVE_MAP_STYLE_URL);
}

function TripStoryExplorer({
  reconstruction,
  tripId,
  isLoading = false,
  state,
  onStateChange,
  initialAreaVisitsByDay,
  onCreateAreaVisit,
  onAddAreaVisitStop,
  onDeleteAreaVisit,
  onMergeStops,
  onRemoveAreaVisitStop,
  onRenameAreaVisit,
  onRenameStop,
  onSetDayNote,
  onSetStopNote,
  onSplitStop,
  onOpenPhotos,
  mobilePane = "map",
  onMobilePaneChange,
  timezoneId,
}: {
  reconstruction: ReconstructionResponse | null;
  tripId?: string;
  isLoading?: boolean;
  state: StoryMapState;
  onStateChange: (state: StoryMapState) => void;
  initialAreaVisitsByDay?: Record<string, AreaVisitsResponse>;
  onCreateAreaVisit?: (
    dayId: string,
    stopIds: string[],
    title: string,
  ) => Promise<void>;
  onAddAreaVisitStop?: (areaVisitId: string, stopId: string) => Promise<void>;
  onDeleteAreaVisit?: (areaVisitId: string) => Promise<void>;
  onMergeStops?: (sourceStopId: string, targetStopId: string) => Promise<void>;
  onRemoveAreaVisitStop?: (
    areaVisitId: string,
    stopId: string,
  ) => Promise<void>;
  onRenameAreaVisit?: (areaVisitId: string, title: string) => Promise<void>;
  onRenameStop?: (stopId: string, title: string) => Promise<void>;
  onSetDayNote?: (dayId: string, note: string) => Promise<void>;
  onSetStopNote?: (stopId: string, note: string) => Promise<void>;
  onSplitStop?: (stopId: string, afterMediaItemId: string) => Promise<void>;
  onOpenPhotos?: () => void;
  mobilePane?: StoryMobilePane;
  onMobilePaneChange?: (pane: StoryMobilePane) => void;
  timezoneId: string;
}) {
  const model = useMemo(
    () => buildStoryModel(reconstruction),
    [reconstruction],
  );
  const filteredModel = useMemo(
    () => filterStoryModel(model, state.contributorFilter),
    [model, state.contributorFilter],
  );
  const selectedStop = filteredModel.stops.find(
    (stop) => stop.id === state.selectedStopId,
  );
  const selectedMedia = filteredModel.media.find(
    (item) => item.id === state.selectedMediaId,
  );
  const activeStopRefs = useRef<Record<string, HTMLElement | null>>({});
  const timelineRef = useRef<HTMLElement | null>(null);
  const latestStateRef = useRef(state);
  const skipNextTimelineSelectionRef = useRef(false);
  const suppressNextTimelineAutoScrollRef = useRef(false);
  const timelinePaneFocusStopRef = useRef<string | null>(null);
  const reducedMotion = useReducedMotion();
  const [galleryMediaId, setGalleryMediaId] = useState<string | null>(null);
  const [galleryPhotoIds, setGalleryPhotoIds] = useState<string[] | null>(null);
  const [galleryScopedPhotos, setGalleryScopedPhotos] = useState<
    GalleryPhoto[] | null
  >(null);
  const [editToolsStopId, setEditToolsStopId] = useState<string | null>(null);
  const [editingStopId, setEditingStopId] = useState<string | null>(null);
  const [stopTitleDraft, setStopTitleDraft] = useState("");
  const [renameStopError, setRenameStopError] = useState("");
  const [savingStopId, setSavingStopId] = useState<string | null>(null);
  const [editingNoteKey, setEditingNoteKey] = useState<string | null>(null);
  const [noteDraft, setNoteDraft] = useState("");
  const [noteError, setNoteError] = useState("");
  const [savingNoteKey, setSavingNoteKey] = useState<string | null>(null);
  const [mergeStopError, setMergeStopError] = useState("");
  const [mergingStopKey, setMergingStopKey] = useState<string | null>(null);
  const [mergePickerStopId, setMergePickerStopId] = useState<string | null>(
    null,
  );
  const [pendingMergeKey, setPendingMergeKey] = useState<string | null>(null);
  const [splitStopId, setSplitStopId] = useState<string | null>(null);
  const [splitStopError, setSplitStopError] = useState("");
  const [splittingStopKey, setSplittingStopKey] = useState<string | null>(null);
  const [pendingSplitKey, setPendingSplitKey] = useState<string | null>(null);
  const [isPhotoRollOpen, setIsPhotoRollOpen] = useState(false);
  const [photoProjectionCache, setPhotoProjectionCache] = useState<
    Record<string, StoryPhotoProjectionResponse>
  >({});
  const [photoProjectionError, setPhotoProjectionError] = useState("");
  const [loadingPhotoProjectionKey, setLoadingPhotoProjectionKey] = useState<
    string | null
  >(null);
  const [areaVisitsByDay, setAreaVisitsByDay] = useState<
    Record<string, AreaVisitsResponse>
  >({});
  const [editingAreaId, setEditingAreaId] = useState<string | null>(null);
  const [areaTitleDraft, setAreaTitleDraft] = useState("");
  const [areaEditError, setAreaEditError] = useState("");
  const [savingAreaActionKey, setSavingAreaActionKey] = useState<string | null>(
    null,
  );
  const [areaSelectionDayId, setAreaSelectionDayId] = useState<string | null>(
    null,
  );
  const [selectedAreaStopIds, setSelectedAreaStopIds] = useState<string[]>([]);
  const [isAreaCreateSheetOpen, setIsAreaCreateSheetOpen] = useState(false);
  const [newAreaTitleDraft, setNewAreaTitleDraft] = useState("");
  const [createAreaError, setCreateAreaError] = useState("");
  const [isCreatingArea, setIsCreatingArea] = useState(false);
  const [expandedMapAreaId, setExpandedMapAreaId] = useState<string | null>(
    null,
  );
  const displayMobilePane = mobilePane === "photos" ? "map" : mobilePane;
  const stopLabelById = useMemo(
    () => new Map(filteredModel.stops.map((stop) => [stop.id, stop.label])),
    [filteredModel.stops],
  );
  const galleryPhotos = useMemo(
    () =>
      filteredModel.media.map((item) =>
        galleryPhotoFromStoryMedia(item, stopLabelById.get(item.stopId)),
      ),
    [filteredModel.media, stopLabelById],
  );
  const browserPhotos = useMemo(() => {
    if (galleryScopedPhotos) {
      return galleryScopedPhotos;
    }
    if (!galleryPhotoIds) {
      return galleryPhotos;
    }
    const scopedIds = new Set(galleryPhotoIds);
    return galleryPhotos.filter((photo) => scopedIds.has(photo.id));
  }, [galleryPhotoIds, galleryPhotos, galleryScopedPhotos]);
  const activePhotoDayId =
    state.selectedDayId ?? reconstruction?.days[0]?.id ?? null;
  const photoProjectionScope = `${tripId ?? "public"}:${
    reconstruction?.latestRun?.id ?? "none"
  }`;
  const activeDayPhotoProjection = activePhotoDayId
    ? photoProjectionCache[`${photoProjectionScope}:day:${activePhotoDayId}`]
    : undefined;
  const photoRollDays = useMemo(() => {
    if (!activeDayPhotoProjection || !activePhotoDayId) {
      if (tripId) {
        return [];
      }
      return (
        reconstruction?.days
          .filter(
            (day) => !state.selectedDayId || day.id === state.selectedDayId,
          )
          .map((day) => ({
            day,
            stops: day.stops
              .map((stop) => ({
                stop,
                photos: filteredModel.media
                  .filter(
                    (item) => item.stopId === stop.id && item.thumbnailUrl,
                  )
                  .map((item) =>
                    galleryPhotoFromStoryMedia(item, displayStopTitle(stop)),
                  ),
              }))
              .filter((section) => section.photos.length > 0),
          }))
          .filter((day) => day.stops.length > 0) ?? []
      );
    }
    const day = reconstruction?.days.find(
      (item) => item.id === activePhotoDayId,
    );
    if (!day) {
      return [];
    }
    return [
      {
        day,
        stops: activeDayPhotoProjection.stops
          .map((stop) => ({
            stop,
            photos: stop.photos.map((photo) =>
              galleryPhotoFromStoryPhoto(photo, stop.title ?? stop.placeName),
            ),
          }))
          .filter((section) => section.photos.length > 0),
      },
    ];
  }, [
    activeDayPhotoProjection,
    activePhotoDayId,
    filteredModel.media,
    reconstruction?.days,
    state.selectedDayId,
    tripId,
  ]);
  const photoRollPhotoCount = useMemo(
    () =>
      photoRollDays.reduce(
        (total, day) =>
          total +
          day.stops.reduce(
            (subtotal, stop) => subtotal + stop.photos.length,
            0,
          ),
        0,
      ),
    [photoRollDays],
  );
  const isPhotoRollVisible = isPhotoRollOpen || mobilePane === "photos";
  const closePhotoRoll = useCallback(() => {
    setIsPhotoRollOpen(false);
    if (mobilePane === "photos") {
      onMobilePaneChange?.("map");
    }
  }, [mobilePane, onMobilePaneChange]);

  const loadDayPhotoProjection = useCallback(
    async (dayId: string) => {
      if (!tripId) {
        return null;
      }
      const cacheKey = `${photoProjectionScope}:day:${dayId}`;
      if (
        photoProjectionCache[cacheKey] ||
        loadingPhotoProjectionKey === cacheKey
      ) {
        return photoProjectionCache[cacheKey];
      }
      setPhotoProjectionError("");
      setLoadingPhotoProjectionKey(cacheKey);
      try {
        const projection = await api.storyDayPhotos(tripId, dayId);
        setPhotoProjectionCache((current) => ({
          ...current,
          [cacheKey]: projection,
        }));
        return projection;
      } catch (error) {
        setPhotoProjectionError(messageFrom(error));
        return null;
      } finally {
        setLoadingPhotoProjectionKey(null);
      }
    },
    [
      loadingPhotoProjectionKey,
      photoProjectionCache,
      photoProjectionScope,
      tripId,
    ],
  );

  const loadStopPhotoProjection = useCallback(
    async (stopId: string) => {
      if (!tripId) {
        return null;
      }
      const cacheKey = `${photoProjectionScope}:stop:${stopId}`;
      if (
        photoProjectionCache[cacheKey] ||
        loadingPhotoProjectionKey === cacheKey
      ) {
        return photoProjectionCache[cacheKey];
      }
      setPhotoProjectionError("");
      setLoadingPhotoProjectionKey(cacheKey);
      try {
        const projection = await api.storyStopPhotos(tripId, stopId);
        setPhotoProjectionCache((current) => ({
          ...current,
          [cacheKey]: projection,
        }));
        return projection;
      } catch (error) {
        setPhotoProjectionError(messageFrom(error));
        return null;
      } finally {
        setLoadingPhotoProjectionKey(null);
      }
    },
    [
      loadingPhotoProjectionKey,
      photoProjectionCache,
      photoProjectionScope,
      tripId,
    ],
  );

  useEffect(() => {
    const runId = reconstruction?.latestRun?.id;
    let cancelled = false;
    if (!tripId && initialAreaVisitsByDay) {
      Promise.resolve().then(() => {
        if (!cancelled) {
          setAreaVisitsByDay(initialAreaVisitsByDay);
        }
      });
      return () => {
        cancelled = true;
      };
    }
    if (!tripId || !runId || reconstruction.days.length === 0) {
      Promise.resolve().then(() => {
        if (!cancelled) {
          setAreaVisitsByDay({});
        }
      });
      return () => {
        cancelled = true;
      };
    }
    Promise.all(
      reconstruction.days.map(async (day) => {
        try {
          return [day.id, await api.areaVisits(tripId, day.id)] as const;
        } catch {
          return [day.id, null] as const;
        }
      }),
    ).then((entries) => {
      if (cancelled) {
        return;
      }
      setAreaVisitsByDay(
        Object.fromEntries(
          entries.flatMap(([dayId, areaVisits]) =>
            areaVisits ? [[dayId, areaVisits]] : [],
          ),
        ),
      );
    });
    return () => {
      cancelled = true;
    };
  }, [initialAreaVisitsByDay, reconstruction, tripId]);

  useEffect(() => {
    if (isPhotoRollVisible && activePhotoDayId) {
      void Promise.resolve().then(() =>
        loadDayPhotoProjection(activePhotoDayId),
      );
    }
  }, [activePhotoDayId, isPhotoRollVisible, loadDayPhotoProjection]);

  useEffect(() => {
    latestStateRef.current = state;
  }, [state]);

  useEffect(() => {
    const normalizedState = normalizeStoryMapState(state, model);
    if (normalizedState !== state) {
      onStateChange(normalizedState);
    }
  }, [model, onStateChange, state]);

  useEffect(() => {
    if (displayMobilePane !== "timeline" || !state.selectedStopId) {
      return;
    }
    if (suppressNextTimelineAutoScrollRef.current) {
      suppressNextTimelineAutoScrollRef.current = false;
      return;
    }
    const element = activeStopRefs.current[state.selectedStopId];
    if (!element) {
      return;
    }
    timelinePaneFocusStopRef.current = state.selectedStopId;
    skipNextTimelineSelectionRef.current = true;
    const frameId = window.requestAnimationFrame(() => {
      element.scrollIntoView({
        block: "center",
        behavior: reducedMotion ? "auto" : "smooth",
      });
    });
    const timeoutId = window.setTimeout(
      () => {
        if (timelinePaneFocusStopRef.current === state.selectedStopId) {
          timelinePaneFocusStopRef.current = null;
        }
      },
      reducedMotion ? 0 : 500,
    );
    return () => {
      window.cancelAnimationFrame(frameId);
      window.clearTimeout(timeoutId);
    };
  }, [displayMobilePane, reducedMotion, state.selectedStopId]);

  useEffect(() => {
    if (!["STOP", "MOMENT"].includes(state.viewMode)) {
      return;
    }
    const elements = Object.values(activeStopRefs.current).filter(
      (element): element is HTMLElement => element !== null,
    );
    if (elements.length === 0 || typeof IntersectionObserver === "undefined") {
      return;
    }
    const timeline = timelineRef.current;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort(
            (left, right) => right.intersectionRatio - left.intersectionRatio,
          )[0];
        const stopId = visible?.target.getAttribute("data-stop-id");
        const dayId = visible?.target.getAttribute("data-day-id");
        const currentState = latestStateRef.current;
        if (
          timelinePaneFocusStopRef.current &&
          timelinePaneFocusStopRef.current === currentState.selectedStopId
        ) {
          return;
        }
        if (skipNextTimelineSelectionRef.current) {
          skipNextTimelineSelectionRef.current = false;
          return;
        }
        if (
          stopId &&
          dayId &&
          stopId !== currentState.selectedStopId &&
          ["STOP", "MOMENT"].includes(currentState.viewMode)
        ) {
          suppressNextTimelineAutoScrollRef.current = true;
          onStateChange(selectStoryStop(currentState, stopId, dayId));
        }
      },
      { root: timeline, threshold: [0.35, 0.7] },
    );
    for (const element of elements) {
      observer.observe(element);
    }
    return () => observer.disconnect();
  }, [filteredModel.stops, onStateChange, state.viewMode]);

  useEffect(() => {
    if (!isPhotoRollVisible) {
      return;
    }
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        closePhotoRoll();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [closePhotoRoll, isPhotoRollVisible]);

  if (isLoading) {
    return (
      <div className="story-empty" aria-busy="true">
        <p>Loading...</p>
      </div>
    );
  }

  if (!reconstruction?.latestRun) {
    return (
      <div className="story-empty">
        <p>
          Refresh the story after adding photos to build the map and timeline.
        </p>
      </div>
    );
  }
  const story = reconstruction;

  function setViewMode(viewMode: ViewMode) {
    if (viewMode === "PLAYBACK") {
      onStateChange(startPlayback(state));
    } else if (viewMode === "TRIP_OVERVIEW") {
      setExpandedMapAreaId(null);
      onStateChange({
        ...state,
        viewMode,
        selectedDayId: null,
        selectedStopId: null,
        selectedMomentId: null,
        selectedMediaId: null,
        mapControlMode: "STORY_CONTROLLED",
      });
    } else if (viewMode === "DAY") {
      setExpandedMapAreaId(null);
      const dayId = state.selectedDayId ?? filteredModel.stops[0]?.dayId;
      if (dayId) {
        onStateChange(selectStoryDay(state, dayId));
      }
    } else {
      onStateChange({ ...state, viewMode, mapControlMode: "STORY_CONTROLLED" });
    }
  }

  function canSelectTimelineStop(): boolean {
    return ["STOP", "MOMENT"].includes(state.viewMode);
  }

  function handleTimelineKey(
    event: KeyboardEvent<HTMLElement>,
    stopId: string,
    dayId: string,
  ) {
    const target = event.target;
    if (
      target instanceof HTMLInputElement ||
      target instanceof HTMLTextAreaElement ||
      target instanceof HTMLSelectElement ||
      (target instanceof HTMLElement && target.isContentEditable)
    ) {
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (canSelectTimelineStop()) {
        onStateChange(selectStoryStop(state, stopId, dayId));
      }
    }
  }

  function focusTimelineStopOnMap(stopId: string, dayId: string) {
    onStateChange(selectStoryStop(state, stopId, dayId));
    onMobilePaneChange?.("map");
  }

  async function openStopPhotos(stopId: string, dayId: string) {
    if (!tripId) {
      const stopMedia = filteredModel.media.filter(
        (item) => item.stopId === stopId,
      );
      const featuredMedia =
        stopMedia.find((item) => item.thumbnailUrl) ?? stopMedia[0];
      if (!featuredMedia) {
        onStateChange(selectStoryStop(state, stopId, dayId));
        return;
      }
      onStateChange(
        selectStoryMedia(
          state,
          featuredMedia.id,
          featuredMedia.momentId,
          stopId,
          dayId,
        ),
      );
      const photos = stopMedia.map((item) =>
        galleryPhotoFromStoryMedia(item, stopLabelById.get(stopId)),
      );
      setGalleryScopedPhotos(photos);
      setGalleryPhotoIds(photos.map((item) => item.id));
      setGalleryMediaId(featuredMedia.id);
      return;
    }
    const projection = await loadStopPhotoProjection(stopId);
    const photos =
      projection?.stops.flatMap((stop) =>
        stop.photos.map((photo) =>
          galleryPhotoFromStoryPhoto(photo, stop.title ?? stop.placeName),
        ),
      ) ?? [];
    const featuredPhoto =
      photos.find((item) => item.thumbnailUrl ?? item.imageUrl) ?? photos[0];
    if (!featuredPhoto) {
      onStateChange(selectStoryStop(state, stopId, dayId));
      return;
    }
    onStateChange(selectStoryStop(state, stopId, dayId));
    setGalleryScopedPhotos(photos);
    setGalleryPhotoIds(photos.map((item) => item.id));
    setGalleryMediaId(featuredPhoto.id);
  }

  function openPhotoRollPhoto(photoId: string, photos: GalleryPhoto[]) {
    const next = filteredModel.media.find((item) => item.id === photoId);
    if (next) {
      onStateChange(
        selectStoryMedia(
          state,
          next.id,
          next.momentId,
          next.stopId,
          next.dayId,
        ),
      );
    }
    setGalleryScopedPhotos(photos);
    setGalleryPhotoIds(photos.map((photo) => photo.id));
    setGalleryMediaId(photoId);
    closePhotoRoll();
  }

  function showDayStops(dayId: string) {
    const firstStop = filteredModel.stops.find((stop) => stop.dayId === dayId);
    skipNextTimelineSelectionRef.current = true;
    setExpandedMapAreaId(null);
    onStateChange({
      ...state,
      viewMode: "STOP",
      selectedDayId: dayId,
      selectedStopId: firstStop?.id ?? null,
      selectedMomentId: null,
      selectedMediaId: null,
      mapControlMode: "STORY_CONTROLLED",
    });
  }

  function displayStopTitle(
    stop: Pick<
      ReconstructionResponse["days"][number]["stops"][number],
      "placeName" | "position" | "title"
    >,
  ): string {
    return stop.title ?? stop.placeName ?? `Stop ${stop.position}`;
  }

  function displayStopPosition(
    stop: Pick<
      ReconstructionResponse["days"][number]["stops"][number],
      "displayPosition" | "position"
    >,
  ): string {
    return stop.displayPosition ?? String(stop.position);
  }

  function displayAreaTitle(area: AreaVisitResponse): string {
    return area.title ?? `Area ${area.sortOrder}`;
  }

  function areaSummary(stops: ReconstructionStopResponse[]): string {
    const photoCount = stops.reduce(
      (total, stop) => total + stop.mediaCount,
      0,
    );
    const travelerCount = new Set(
      stops.flatMap((stop) =>
        stop.moments.flatMap((moment) =>
          moment.media.map((item) => item.contributorMemberId),
        ),
      ),
    ).size;
    return `${stops.length} stops · ${photoCount} photos · ${travelerCount} travelers`;
  }

  function areaForStop(
    day: ReconstructionDayResponse,
    stopId: string,
  ): { area: AreaVisitResponse; stops: ReconstructionStopResponse[] } | null {
    const areaVisits = areaVisitsByDay[day.id];
    if (!areaVisits || areaVisits.areas.length === 0) {
      return null;
    }
    const stopById = new Map(day.stops.map((stop) => [stop.id, stop]));
    for (const area of areaVisits.areas) {
      if (!area.stops.some((stop) => stop.id === stopId)) {
        continue;
      }
      const stops = area.stops
        .map((areaStop) => stopById.get(areaStop.id))
        .filter((stop): stop is ReconstructionStopResponse => Boolean(stop));
      return { area, stops };
    }
    return null;
  }

  function areaEditableEdges(
    day: ReconstructionDayResponse,
    area: AreaVisitResponse,
  ): {
    previous: ReconstructionStopResponse | null;
    next: ReconstructionStopResponse | null;
  } {
    const areaStopIds = new Set(area.stops.map((stop) => stop.id));
    const standaloneStopIds = new Set(
      areaVisitsByDay[day.id]?.standaloneStops.map((stop) => stop.id) ?? [],
    );
    const areaIndexes = day.stops
      .map((stop, index) => (areaStopIds.has(stop.id) ? index : -1))
      .filter((index) => index >= 0);
    if (areaIndexes.length === 0) {
      return { previous: null, next: null };
    }
    const firstIndex = Math.min(...areaIndexes);
    const lastIndex = Math.max(...areaIndexes);
    const previous = day.stops[firstIndex - 1] ?? null;
    const next = day.stops[lastIndex + 1] ?? null;
    return {
      previous:
        previous && standaloneStopIds.has(previous.id) ? previous : null,
      next: next && standaloneStopIds.has(next.id) ? next : null,
    };
  }

  function stopIsStandaloneForAreaSelection(
    day: ReconstructionDayResponse,
    stopId: string,
  ): boolean {
    const areaVisits = areaVisitsByDay[day.id];
    if (!areaVisits) {
      return false;
    }
    return areaVisits.standaloneStops.some((stop) => stop.id === stopId);
  }

  function cancelAreaSelection() {
    setAreaSelectionDayId(null);
    setSelectedAreaStopIds([]);
    setIsAreaCreateSheetOpen(false);
    setNewAreaTitleDraft("");
    setCreateAreaError("");
  }

  function startAreaSelection(day: ReconstructionDayResponse) {
    setAreaSelectionDayId(day.id);
    setSelectedAreaStopIds([]);
    setIsAreaCreateSheetOpen(false);
    setNewAreaTitleDraft("");
    setCreateAreaError("");
    setEditToolsStopId(null);
    setEditingAreaId(null);
  }

  function toggleAreaSelectionStop(
    day: ReconstructionDayResponse,
    stop: ReconstructionStopResponse,
  ) {
    if (areaSelectionDayId !== day.id) {
      return;
    }
    if (!stopIsStandaloneForAreaSelection(day, stop.id)) {
      setCreateAreaError("This stop already belongs to an area.");
      return;
    }
    const selectedSet = new Set(selectedAreaStopIds);
    const orderedIds = day.stops.map((dayStop) => dayStop.id);
    const stopIndex = orderedIds.indexOf(stop.id);
    if (selectedSet.has(stop.id)) {
      const selectedIndexes = selectedAreaStopIds
        .map((stopId) => orderedIds.indexOf(stopId))
        .filter((index) => index >= 0);
      if (
        selectedIndexes.length > 1 &&
        stopIndex !== Math.min(...selectedIndexes) &&
        stopIndex !== Math.max(...selectedIndexes)
      ) {
        setCreateAreaError("Remove stops from either end of the selection.");
        return;
      }
      selectedSet.delete(stop.id);
    } else {
      selectedSet.add(stop.id);
    }
    const nextIndexes = Array.from(selectedSet)
      .map((stopId) => orderedIds.indexOf(stopId))
      .filter((index) => index >= 0)
      .sort((left, right) => left - right);
    const isContiguous =
      nextIndexes.length === 0 ||
      nextIndexes.every(
        (index, position) =>
          position === 0 || index === nextIndexes[position - 1] + 1,
      );
    if (!isContiguous) {
      setCreateAreaError("Select one contiguous run of stops.");
      return;
    }
    setSelectedAreaStopIds(nextIndexes.map((index) => orderedIds[index]));
    setCreateAreaError("");
  }

  function openCreateAreaSheet(day: ReconstructionDayResponse) {
    if (selectedAreaStopIds.length < 3) {
      setCreateAreaError("Select at least 3 stops.");
      return;
    }
    const selectedIndexes = selectedAreaStopIds
      .map((stopId) => day.stops.findIndex((stop) => stop.id === stopId))
      .filter((index) => index >= 0);
    const firstStop = day.stops[Math.min(...selectedIndexes)];
    const lastStop = day.stops[Math.max(...selectedIndexes)];
    setNewAreaTitleDraft(
      firstStop && lastStop
        ? `${displayStopTitle(firstStop)} to ${displayStopTitle(lastStop)}`
        : "",
    );
    setIsAreaCreateSheetOpen(true);
    setCreateAreaError("");
  }

  async function createSelectedArea(day: ReconstructionDayResponse) {
    const title = newAreaTitleDraft.trim();
    if (!onCreateAreaVisit || !title || selectedAreaStopIds.length < 3) {
      return;
    }
    setIsCreatingArea(true);
    setCreateAreaError("");
    try {
      await onCreateAreaVisit(day.id, selectedAreaStopIds, title);
      cancelAreaSelection();
    } catch (error) {
      setCreateAreaError(messageFrom(error));
    } finally {
      setIsCreatingArea(false);
    }
  }

  function timelineBranchInfo(
    groups: Map<string, ReconstructionStopResponse[]>,
    stop: ReconstructionStopResponse,
  ): { dayHasBranches: boolean; stopClassName: string } {
    if (groups.size === 0) {
      return { dayHasBranches: false, stopClassName: "" };
    }
    const position = timelineForkPosition(stop);
    const group = position ? groups.get(position.base) : undefined;
    if (!position || !group || group.length < 2) {
      return { dayHasBranches: true, stopClassName: "" };
    }
    const branchIndex = group.findIndex(
      (groupStop) => groupStop.id === stop.id,
    );
    return {
      dayHasBranches: true,
      stopClassName: branchIndex > 0 ? "timeline-stop-branch" : "",
    };
  }

  function timelineForkGroups(
    day: ReconstructionDayResponse,
  ): Map<string, ReconstructionStopResponse[]> {
    const groups = new Map<string, ReconstructionStopResponse[]>();
    for (const stop of day.stops) {
      const position = timelineForkPosition(stop);
      if (!position?.suffix) {
        continue;
      }
      const group = groups.get(position.base) ?? [];
      group.push(stop);
      groups.set(position.base, group);
    }
    for (const [base, group] of groups) {
      if (group.length < 2) {
        groups.delete(base);
      }
    }
    return groups;
  }

  function timelineForkPosition(
    stop: ReconstructionStopResponse,
  ): { base: string; suffix: string } | null {
    const displayPosition = displayStopPosition(stop);
    const match = /^(\d+)([A-Za-z]+)$/.exec(displayPosition);
    return match ? { base: match[1], suffix: match[2] } : null;
  }

  function mergeCandidateStops(
    day: ReconstructionDayResponse,
    stop: ReconstructionStopResponse,
    forkGroups: Map<string, ReconstructionStopResponse[]>,
  ): ReconstructionStopResponse[] {
    const candidateIds = new Set<string>();
    for (const leg of model.legs) {
      if (leg.dayId !== day.id) {
        continue;
      }
      if (leg.fromStopId === stop.id) {
        candidateIds.add(leg.toStopId);
      }
      if (leg.toStopId === stop.id) {
        candidateIds.add(leg.fromStopId);
      }
    }
    const position = timelineForkPosition(stop);
    const forkSiblings = position ? forkGroups.get(position.base) : undefined;
    for (const sibling of forkSiblings ?? []) {
      if (sibling.id !== stop.id) {
        candidateIds.add(sibling.id);
      }
    }
    if (candidateIds.size === 0) {
      const stopIndex = day.stops.findIndex(
        (candidate) => candidate.id === stop.id,
      );
      for (const neighbor of [
        day.stops[stopIndex - 1],
        day.stops[stopIndex + 1],
      ]) {
        if (neighbor) {
          candidateIds.add(neighbor.id);
        }
      }
    }
    return day.stops.filter((candidate) => candidateIds.has(candidate.id));
  }

  function startEditingArea(area: AreaVisitResponse) {
    setEditingAreaId(area.id);
    setAreaTitleDraft(displayAreaTitle(area));
    setAreaEditError("");
  }

  async function saveAreaTitle(area: AreaVisitResponse) {
    const nextTitle = areaTitleDraft.trim();
    if (!onRenameAreaVisit || !nextTitle) {
      return;
    }
    setSavingAreaActionKey(`rename:${area.id}`);
    setAreaEditError("");
    try {
      await onRenameAreaVisit(area.id, nextTitle);
      setEditingAreaId(null);
      setAreaTitleDraft("");
    } catch (error) {
      setAreaEditError(messageFrom(error));
    } finally {
      setSavingAreaActionKey(null);
    }
  }

  async function addStopToArea(area: AreaVisitResponse, stopId: string) {
    if (!onAddAreaVisitStop) {
      return;
    }
    const key = `add:${area.id}:${stopId}`;
    setSavingAreaActionKey(key);
    setAreaEditError("");
    try {
      await onAddAreaVisitStop(area.id, stopId);
    } catch (error) {
      setAreaEditError(messageFrom(error));
    } finally {
      setSavingAreaActionKey(null);
    }
  }

  async function removeStopFromArea(area: AreaVisitResponse, stopId: string) {
    if (!onRemoveAreaVisitStop) {
      return;
    }
    const key = `remove:${area.id}:${stopId}`;
    setSavingAreaActionKey(key);
    setAreaEditError("");
    try {
      await onRemoveAreaVisitStop(area.id, stopId);
    } catch (error) {
      setAreaEditError(messageFrom(error));
    } finally {
      setSavingAreaActionKey(null);
    }
  }

  async function deleteArea(area: AreaVisitResponse) {
    if (!onDeleteAreaVisit) {
      return;
    }
    const key = `delete:${area.id}`;
    setSavingAreaActionKey(key);
    setAreaEditError("");
    try {
      await onDeleteAreaVisit(area.id);
      setEditingAreaId(null);
      setAreaTitleDraft("");
    } catch (error) {
      setAreaEditError(messageFrom(error));
    } finally {
      setSavingAreaActionKey(null);
    }
  }

  function startRenamingStop(
    stop: ReconstructionResponse["days"][number]["stops"][number],
  ) {
    setEditToolsStopId(stop.id);
    setEditingStopId(stop.id);
    setStopTitleDraft(displayStopTitle(stop));
    setRenameStopError("");
  }

  function startEditingNote(key: string, note: string | null | undefined) {
    setEditingNoteKey(key);
    setNoteDraft(note ?? "");
    setNoteError("");
  }

  async function saveStopTitle(stopId: string) {
    const nextTitle = stopTitleDraft.trim();
    if (!onRenameStop || !nextTitle) {
      return;
    }
    setSavingStopId(stopId);
    setRenameStopError("");
    try {
      await onRenameStop(stopId, nextTitle);
      setEditingStopId(null);
      setStopTitleDraft("");
    } catch (error) {
      setRenameStopError(messageFrom(error));
    } finally {
      setSavingStopId(null);
    }
  }

  async function saveTimelineNote(
    kind: "day" | "stop",
    id: string,
    key: string,
  ) {
    const save = kind === "day" ? onSetDayNote : onSetStopNote;
    if (!save) {
      return;
    }
    setSavingNoteKey(key);
    setNoteError("");
    try {
      await save(id, noteDraft);
      setEditingNoteKey(null);
      setNoteDraft("");
    } catch (error) {
      setNoteError(messageFrom(error));
    } finally {
      setSavingNoteKey(null);
    }
  }

  async function mergeTimelineStop(
    mergeCandidateStopId: string,
    selectedTargetStopId: string,
    dayId: string,
  ) {
    if (!onMergeStops) {
      return;
    }
    const key = `${mergeCandidateStopId}:${selectedTargetStopId}`;
    if (pendingMergeKey !== key) {
      setPendingMergeKey(key);
      setMergeStopError("");
      return;
    }
    setMergingStopKey(key);
    setMergeStopError("");
    try {
      await onMergeStops(mergeCandidateStopId, selectedTargetStopId);
      onStateChange(selectStoryStop(state, selectedTargetStopId, dayId));
      setPendingMergeKey(null);
      setMergePickerStopId(null);
      setEditToolsStopId(null);
      setEditingNoteKey(null);
    } catch (error) {
      setMergeStopError(`Could not merge stops. ${messageFrom(error)}`);
    } finally {
      setMergingStopKey(null);
    }
  }

  function orderedStopMedia(stop: ReconstructionStopResponse) {
    return stop.moments.flatMap((moment) => moment.media);
  }

  async function splitStopAfterMedia(
    stopId: string,
    afterMediaItemId: string,
    dayId: string,
  ) {
    if (!onSplitStop) {
      return;
    }
    const key = `${stopId}:${afterMediaItemId}`;
    if (pendingSplitKey !== key) {
      setPendingSplitKey(key);
      setSplitStopError("");
      return;
    }
    setSplittingStopKey(key);
    setSplitStopError("");
    try {
      await onSplitStop(stopId, afterMediaItemId);
      onStateChange(selectStoryStop(state, stopId, dayId));
      setSplitStopId(null);
      setEditToolsStopId(null);
      setPendingSplitKey(null);
    } catch (error) {
      setSplitStopError(`Could not split stop. ${messageFrom(error)}`);
    } finally {
      setSplittingStopKey(null);
    }
  }

  function navigateStorySummary(direction: "previous" | "next") {
    if (!summaryNavigator) {
      return;
    }
    if (summaryNavigator.type === "day") {
      const nextDay =
        story.days[
          direction === "previous"
            ? summaryNavigator.previousIndex
            : summaryNavigator.nextIndex
        ];
      if (nextDay) {
        onStateChange(selectStoryDay(state, nextDay.id));
      }
      return;
    }
    const nextStop =
      activeDay?.stops[
        direction === "previous"
          ? summaryNavigator.previousIndex
          : summaryNavigator.nextIndex
      ];
    if (nextStop && activeDay) {
      const nextAreaContext = areaForStop(activeDay, nextStop.id);
      if (nextAreaContext?.area.id !== expandedMapAreaId) {
        setExpandedMapAreaId(null);
      }
      onStateChange(selectStoryStop(state, nextStop.id, activeDay.id));
    }
  }

  const selectedLabel =
    selectedMedia?.filename ?? selectedStop?.label ?? "Trip overview";
  const activeDay = story.days.find((day) => day.id === state.selectedDayId);
  const activeDayIndex = activeDay
    ? story.days.findIndex((day) => day.id === activeDay.id)
    : -1;
  const selectedStopDetail =
    story.days
      .flatMap((day) => day.stops)
      .find((stop) => stop.id === state.selectedStopId) ?? null;
  const selectedStopIndex =
    activeDay && selectedStopDetail
      ? activeDay.stops.findIndex((stop) => stop.id === selectedStopDetail.id)
      : -1;
  const selectedAreaContext =
    activeDay && selectedStopDetail
      ? areaForStop(activeDay, selectedStopDetail.id)
      : null;
  const isSelectedAreaExpanded =
    Boolean(selectedAreaContext) &&
    selectedAreaContext?.area.id === expandedMapAreaId;
  const isCollapsedAreaSelected =
    Boolean(selectedAreaContext) && !isSelectedAreaExpanded;
  const selectedAreaStopIndexes =
    activeDay && selectedAreaContext
      ? selectedAreaContext.stops
          .map((stop) =>
            activeDay.stops.findIndex((dayStop) => dayStop.id === stop.id),
          )
          .filter((index) => index >= 0)
      : [];
  const summaryNavigator = (() => {
    if (!activeDay) {
      return null;
    }
    if (["STOP", "MOMENT"].includes(state.viewMode)) {
      const total = activeDay.stops.length;
      if (total === 0) {
        return null;
      }
      const currentIndex = selectedStopIndex >= 0 ? selectedStopIndex : -1;
      if (isCollapsedAreaSelected && selectedAreaStopIndexes.length > 0) {
        const firstAreaIndex = Math.min(...selectedAreaStopIndexes);
        const lastAreaIndex = Math.max(...selectedAreaStopIndexes);
        return {
          type: "stop" as const,
          label: `${firstAreaIndex + 1}/${total}`,
          previousDisabled: firstAreaIndex <= 0,
          nextDisabled: lastAreaIndex >= total - 1,
          previousIndex: firstAreaIndex - 1,
          nextIndex: lastAreaIndex + 1,
        };
      }
      return {
        type: "stop" as const,
        label: currentIndex >= 0 ? `${currentIndex + 1}/${total}` : "All",
        previousDisabled: currentIndex <= 0,
        nextDisabled: currentIndex >= total - 1,
        previousIndex: currentIndex - 1,
        nextIndex: currentIndex >= 0 ? currentIndex + 1 : 0,
      };
    }
    const total = story.days.length;
    if (total === 0 || activeDayIndex < 0) {
      return null;
    }
    return {
      type: "day" as const,
      label: `${activeDayIndex + 1}/${total}`,
      previousDisabled: activeDayIndex <= 0,
      nextDisabled: activeDayIndex >= total - 1,
      previousIndex: activeDayIndex - 1,
      nextIndex: activeDayIndex + 1,
    };
  })();
  const selectedStopTitle = selectedStopDetail
    ? isCollapsedAreaSelected && selectedAreaContext
      ? displayAreaTitle(selectedAreaContext.area)
      : displayStopTitle(selectedStopDetail)
    : (selectedStop?.label ?? null);
  const selectedStopSummary = selectedStopDetail
    ? isCollapsedAreaSelected && selectedAreaContext
      ? areaSummary(selectedAreaContext.stops)
      : `${selectedStopDetail.mediaCount} photos · ${selectedStopDetail.contributorCount} travelers`
    : activeDay
      ? `${activeDay.stops.length} stops · ${activeDay.stops.reduce(
          (total, stop) => total + stop.mediaCount,
          0,
        )} photos`
      : "Select a stop on the map to see its note here.";
  const selectedNote =
    (isCollapsedAreaSelected ? "" : selectedStopDetail?.note?.trim()) ||
    activeDay?.note?.trim() ||
    "";
  const activeTimelineDay = activeDay ?? story.days[0] ?? null;
  const timelineDays = activeTimelineDay ? [activeTimelineDay] : [];

  return (
    <div
      className={`story-explorer story-shell story-mobile-pane-${displayMobilePane}`}
    >
      <div className="story-map-panel">
        <StoryMapCanvas
          model={filteredModel}
          state={state}
          areaVisitsByDay={areaVisitsByDay}
          expandedAreaId={expandedMapAreaId}
          activeDayLabel={activeDay ? storyDayLabel(activeDay) : null}
          canOpenActiveDayPhotos={
            Boolean(onOpenPhotos) &&
            Boolean(
              activeDay?.stops.some((stop) => stop.mediaCount > 0) ?? false,
            )
          }
          onOpenActiveDayPhotos={onOpenPhotos}
          onStateChange={onStateChange}
          onExpandedAreaChange={setExpandedMapAreaId}
          onDayMarkerClick={showDayStops}
          onStopMarkerClick={openStopPhotos}
          reducedMotion={reducedMotion}
        />
        <div className="story-selected-stop-summary" aria-live="polite">
          <div>
            <span>
              {isCollapsedAreaSelected
                ? "Selected area"
                : selectedStop
                  ? "Selected stop"
                  : activeDay
                    ? "Selected day"
                    : "Map note"}
            </span>
            <strong>
              {selectedStopTitle
                ? selectedStopTitle
                : activeDay
                  ? storyDayLabel(activeDay)
                  : "No stop selected"}
            </strong>
            <p>{selectedStopSummary}</p>
            {selectedNote ? (
              <p className="story-selected-note">{selectedNote}</p>
            ) : null}
          </div>
          <div className="story-summary-actions">
            {summaryNavigator ? (
              <div
                className="story-summary-pager"
                aria-label={
                  summaryNavigator.type === "stop"
                    ? "Navigate stops"
                    : "Navigate days"
                }
              >
                <button
                  type="button"
                  aria-label={
                    summaryNavigator.type === "stop"
                      ? "Previous stop"
                      : "Previous day"
                  }
                  disabled={summaryNavigator.previousDisabled}
                  onClick={() => navigateStorySummary("previous")}
                >
                  ‹
                </button>
                <span>{summaryNavigator.label}</span>
                <button
                  type="button"
                  aria-label={
                    summaryNavigator.type === "stop" ? "Next stop" : "Next day"
                  }
                  disabled={summaryNavigator.nextDisabled}
                  onClick={() => navigateStorySummary("next")}
                >
                  ›
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </div>

      <aside className="story-side-panel">
        <div className="story-panel-header">
          <div>
            <p className="eyebrow">
              {activeDay ? storyDayDateLabel(activeDay) : "Timeline"}
            </p>
            <h3>{activeDay?.title ?? activeDay?.date ?? selectedLabel}</h3>
            <p>Follow the route through days, stops, and photo moments.</p>
          </div>
          <div className="story-panel-actions">
            <button
              type="button"
              onClick={() => onStateChange(followStory(state))}
              disabled={state.mapControlMode === "STORY_CONTROLLED"}
            >
              Follow
            </button>
            <button
              type="button"
              onClick={() =>
                onStateChange(advancePlayback(state, filteredModel))
              }
            >
              Play
            </button>
            {galleryPhotos.length > 0 ? (
              <button
                type="button"
                onClick={() => {
                  setGalleryScopedPhotos(null);
                  setGalleryPhotoIds(null);
                  setGalleryMediaId(
                    state.selectedMediaId ?? galleryPhotos[0]?.id ?? null,
                  );
                }}
              >
                Browse photos
              </button>
            ) : null}
          </div>
        </div>
        <div className="story-toolbar" aria-label="Story controls">
          <div className="story-scope-summary">
            <span>{activeDay?.title ?? activeDay?.date ?? "Whole trip"}</span>
            <small>
              {filteredModel.stops.length} stops · {filteredModel.media.length}{" "}
              photos
            </small>
          </div>
          <div className="story-day-tabs" role="group" aria-label="Story days">
            <button
              type="button"
              className={state.viewMode === "TRIP_OVERVIEW" ? "active" : ""}
              onClick={() => setViewMode("TRIP_OVERVIEW")}
            >
              All
            </button>
            {story.days.map((day) => (
              <button
                aria-pressed={state.selectedDayId === day.id}
                className={
                  state.viewMode === "DAY" && state.selectedDayId === day.id
                    ? "active"
                    : ""
                }
                key={day.id}
                type="button"
                onClick={() => onStateChange(selectStoryDay(state, day.id))}
              >
                {storyDayDateLabel(day)}
              </button>
            ))}
          </div>
          <div
            className="segmented-control"
            role="group"
            aria-label="View mode"
          >
            {(["DAY", "STOP", "MOMENT", "PLAYBACK"] as ViewMode[]).map(
              (viewMode) => (
                <button
                  aria-pressed={state.viewMode === viewMode}
                  className={state.viewMode === viewMode ? "active" : ""}
                  key={viewMode}
                  type="button"
                  onClick={() => setViewMode(viewMode)}
                >
                  {storyViewLabel(viewMode)}
                </button>
              ),
            )}
          </div>
          <label className="compact-field">
            Traveler
            <select
              value={state.contributorFilter}
              onChange={(event) =>
                onStateChange(setContributorFilter(state, event.target.value))
              }
            >
              <option value={EVERYONE}>Everyone</option>
              {model.contributors.map((contributor) => (
                <option key={contributor.id} value={contributor.id}>
                  {contributor.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        {photoRollDays.length > 0 ||
        (activeDay?.stops.some((stop) => stop.mediaCount > 0) ?? false) ? (
          <div className="story-photo-roll-launch">
            <div>
              <strong>
                {activeDay
                  ? `${storyDayLabel(activeDay)} photos`
                  : "Trip photos"}
              </strong>
              <span>
                {photoRollPhotoCount ||
                  activeDay?.stops.reduce(
                    (total, stop) => total + stop.mediaCount,
                    0,
                  ) ||
                  0}{" "}
                photos grouped by stop
              </span>
            </div>
            <button
              type="button"
              onClick={() => {
                setIsPhotoRollOpen(true);
                if (activePhotoDayId) {
                  void loadDayPhotoProjection(activePhotoDayId);
                }
              }}
            >
              Browse day photos
            </button>
          </div>
        ) : null}
        {photoProjectionError ? (
          <p className="error">{photoProjectionError}</p>
        ) : null}
        <section
          className="story-timeline"
          aria-label="Chronological timeline"
          ref={timelineRef}
        >
          <p className="screen-reader-map-summary">
            Map alternative: {filteredModel.stops.length} stops,{" "}
            {filteredModel.media.length} photos, selected {selectedLabel}.
          </p>
          {story.days.length > 0 ? (
            <div
              className="timeline-day-strip"
              role="group"
              aria-label="Timeline days"
            >
              {story.days.map((day) => {
                const dateParts = timelineDayDateParts(day);
                const isActive = activeTimelineDay?.id === day.id;
                return (
                  <button
                    type="button"
                    className={isActive ? "active" : ""}
                    aria-pressed={isActive}
                    key={day.id}
                    onClick={() => onStateChange(selectStoryDay(state, day.id))}
                  >
                    <span>{dateParts.weekday}</span>
                    <strong>{dateParts.day}</strong>
                  </button>
                );
              })}
            </div>
          ) : null}
          <div className="timeline-day-list">
            {timelineDays.map((day) => {
              const forkGroups = timelineForkGroups(day);
              const dayHasBranches = forkGroups.size > 0;
              return (
                <article
                  className={`timeline-day ${
                    state.selectedDayId === day.id ? "active" : ""
                  } ${dayHasBranches ? "has-branches" : ""}`}
                  key={day.id}
                >
                  <div className="timeline-day-heading">
                    <button
                      type="button"
                      className="timeline-day-button"
                      onClick={() =>
                        onStateChange(selectStoryDay(state, day.id))
                      }
                    >
                      <span>{storyDayLabel(day)}</span>
                      <small>{day.date}</small>
                    </button>
                    <div className="timeline-day-actions">
                      {onCreateAreaVisit ? (
                        areaSelectionDayId === day.id ? (
                          <button
                            type="button"
                            className="timeline-note-button"
                            onClick={cancelAreaSelection}
                          >
                            Cancel area
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="timeline-note-button"
                            disabled={
                              day.stops.length < 3 || !areaVisitsByDay[day.id]
                            }
                            onClick={() => startAreaSelection(day)}
                          >
                            Create area
                          </button>
                        )
                      ) : null}
                      {onSetDayNote ? (
                        <button
                          type="button"
                          className="timeline-note-button"
                          onClick={() =>
                            startEditingNote(`day:${day.id}`, day.note)
                          }
                        >
                          {day.note ? "Edit note" : "Add note"}
                        </button>
                      ) : null}
                    </div>
                  </div>
                  {editingNoteKey === `day:${day.id}` ? (
                    <form
                      className="timeline-note-form"
                      onSubmit={(event) => {
                        event.preventDefault();
                        void saveTimelineNote("day", day.id, `day:${day.id}`);
                      }}
                    >
                      <label>
                        Day note
                        <textarea
                          autoFocus
                          value={noteDraft}
                          onChange={(event) => setNoteDraft(event.target.value)}
                          maxLength={2000}
                          rows={3}
                        />
                      </label>
                      <div className="button-row">
                        <button
                          type="submit"
                          disabled={savingNoteKey === `day:${day.id}`}
                        >
                          Save
                        </button>
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => {
                            setEditingNoteKey(null);
                            setNoteDraft("");
                            setNoteError("");
                          }}
                        >
                          Cancel
                        </button>
                      </div>
                      {noteError ? <p className="error">{noteError}</p> : null}
                    </form>
                  ) : day.note ? (
                    <p className="timeline-note-preview">{day.note}</p>
                  ) : null}
                  {areaSelectionDayId === day.id ? (
                    <div className="timeline-area-selection-row">
                      <strong>
                        {selectedAreaStopIds.length} stops selected
                      </strong>
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={cancelAreaSelection}
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        disabled={selectedAreaStopIds.length < 3}
                        onClick={() => openCreateAreaSheet(day)}
                      >
                        Create area
                      </button>
                    </div>
                  ) : null}
                  {areaSelectionDayId === day.id && isAreaCreateSheetOpen ? (
                    <form
                      className="timeline-area-create-sheet"
                      onSubmit={(event) => {
                        event.preventDefault();
                        void createSelectedArea(day);
                      }}
                    >
                      <label>
                        Area name
                        <input
                          autoFocus
                          value={newAreaTitleDraft}
                          onChange={(event) =>
                            setNewAreaTitleDraft(event.target.value)
                          }
                          maxLength={255}
                          required
                        />
                      </label>
                      <div className="button-row">
                        <button
                          type="submit"
                          disabled={isCreatingArea || !newAreaTitleDraft.trim()}
                        >
                          Confirm
                        </button>
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => {
                            setIsAreaCreateSheetOpen(false);
                            setNewAreaTitleDraft("");
                          }}
                        >
                          Cancel
                        </button>
                      </div>
                    </form>
                  ) : null}
                  {areaSelectionDayId === day.id && createAreaError ? (
                    <p className="error">{createAreaError}</p>
                  ) : null}
                  {day.stops.map((stop) => {
                    const isEditingTools = editToolsStopId === stop.id;
                    const isAreaSelectionMode = areaSelectionDayId === day.id;
                    const isAreaStopSelected =
                      isAreaSelectionMode &&
                      selectedAreaStopIds.includes(stop.id);
                    const canEditStop =
                      !isAreaSelectionMode &&
                      (onRenameStop ||
                        onSetStopNote ||
                        onMergeStops ||
                        onSplitStop);
                    const mergeCandidates = mergeCandidateStops(
                      day,
                      stop,
                      forkGroups,
                    );
                    const mergeCandidateIds = new Set(
                      mergeCandidates.map((candidate) => candidate.id),
                    );
                    const mergeSourceStop = mergePickerStopId
                      ? (day.stops.find(
                          (candidate) => candidate.id === mergePickerStopId,
                        ) ?? null)
                      : null;
                    const canMergeHere =
                      Boolean(onMergeStops) &&
                      mergeSourceStop !== null &&
                      mergeSourceStop.id !== stop.id &&
                      mergeCandidateIds.has(mergeSourceStop.id);
                    const mergeHereKey = mergeSourceStop
                      ? `${mergeSourceStop.id}:${stop.id}`
                      : null;
                    const isPendingMergeHere =
                      Boolean(mergeHereKey) && pendingMergeKey === mergeHereKey;
                    const stopMedia = orderedStopMedia(stop);
                    const areaContext = areaForStop(day, stop.id);
                    const canSelectForArea =
                      isAreaSelectionMode &&
                      stopIsStandaloneForAreaSelection(day, stop.id);
                    const isFirstAreaStop =
                      areaContext?.stops[0]?.id === stop.id;
                    const isLastAreaStop =
                      areaContext?.stops[areaContext.stops.length - 1]?.id ===
                      stop.id;
                    const canEditArea =
                      onRenameAreaVisit ||
                      onAddAreaVisitStop ||
                      onRemoveAreaVisitStop ||
                      onDeleteAreaVisit;
                    const areaEdges = areaContext
                      ? areaEditableEdges(day, areaContext.area)
                      : null;
                    const previousAreaStop = areaEdges?.previous ?? null;
                    const nextAreaStop = areaEdges?.next ?? null;
                    const timelineBranch = timelineBranchInfo(forkGroups, stop);
                    return (
                      <div
                        className={
                          areaContext
                            ? `timeline-stop-stack in-area ${
                                isFirstAreaStop ? "area-start" : ""
                              } ${isLastAreaStop ? "area-end" : ""}`
                            : "timeline-stop-stack"
                        }
                        key={stop.id}
                      >
                        {areaContext && isFirstAreaStop ? (
                          <div className="timeline-area-heading">
                            <div className="timeline-area-heading-main">
                              <span className="timeline-area-kicker">
                                Area {areaContext.area.sortOrder}
                              </span>
                              <strong>
                                {displayAreaTitle(areaContext.area)}
                              </strong>
                              <small>{areaSummary(areaContext.stops)}</small>
                            </div>
                            {canEditArea ? (
                              <button
                                type="button"
                                className="timeline-icon-button"
                                aria-expanded={
                                  editingAreaId === areaContext.area.id
                                }
                                aria-label={
                                  editingAreaId === areaContext.area.id
                                    ? `Close editing tools for ${displayAreaTitle(areaContext.area)}`
                                    : `Edit ${displayAreaTitle(areaContext.area)}`
                                }
                                title={
                                  editingAreaId === areaContext.area.id
                                    ? "Done"
                                    : "Edit area"
                                }
                                onClick={() => {
                                  if (editingAreaId === areaContext.area.id) {
                                    setEditingAreaId(null);
                                    setAreaTitleDraft("");
                                    setAreaEditError("");
                                  } else {
                                    startEditingArea(areaContext.area);
                                  }
                                }}
                              >
                                <TimelineActionIcon
                                  name={
                                    editingAreaId === areaContext.area.id
                                      ? "check"
                                      : "edit"
                                  }
                                />
                              </button>
                            ) : null}
                            {editingAreaId === areaContext.area.id ? (
                              <div className="timeline-area-edit-panel">
                                {onRenameAreaVisit ? (
                                  <form
                                    className="timeline-stop-rename"
                                    onSubmit={(event) => {
                                      event.preventDefault();
                                      void saveAreaTitle(areaContext.area);
                                    }}
                                  >
                                    <label>
                                      Area name
                                      <input
                                        autoFocus
                                        value={areaTitleDraft}
                                        onChange={(event) =>
                                          setAreaTitleDraft(event.target.value)
                                        }
                                        onKeyDown={(event) =>
                                          event.stopPropagation()
                                        }
                                        maxLength={255}
                                        required
                                      />
                                    </label>
                                    <div className="timeline-inline-actions">
                                      <button
                                        type="submit"
                                        className="timeline-icon-button"
                                        aria-label="Save area name"
                                        title="Save"
                                        disabled={
                                          savingAreaActionKey ===
                                            `rename:${areaContext.area.id}` ||
                                          !areaTitleDraft.trim()
                                        }
                                      >
                                        <TimelineActionIcon name="check" />
                                      </button>
                                      <button
                                        type="button"
                                        className="timeline-icon-button"
                                        aria-label="Cancel area renaming"
                                        title="Cancel"
                                        onClick={() => {
                                          setEditingAreaId(null);
                                          setAreaTitleDraft("");
                                          setAreaEditError("");
                                        }}
                                      >
                                        <TimelineActionIcon name="x" />
                                      </button>
                                    </div>
                                  </form>
                                ) : null}
                                {onAddAreaVisitStop &&
                                (previousAreaStop || nextAreaStop) ? (
                                  <div className="timeline-area-edge-tools">
                                    {previousAreaStop ? (
                                      <button
                                        type="button"
                                        className="timeline-tool-button"
                                        disabled={
                                          savingAreaActionKey ===
                                          `add:${areaContext.area.id}:${previousAreaStop.id}`
                                        }
                                        onClick={() =>
                                          void addStopToArea(
                                            areaContext.area,
                                            previousAreaStop.id,
                                          )
                                        }
                                      >
                                        Add before:{" "}
                                        {displayStopPosition(previousAreaStop)}
                                      </button>
                                    ) : null}
                                    {nextAreaStop ? (
                                      <button
                                        type="button"
                                        className="timeline-tool-button"
                                        disabled={
                                          savingAreaActionKey ===
                                          `add:${areaContext.area.id}:${nextAreaStop.id}`
                                        }
                                        onClick={() =>
                                          void addStopToArea(
                                            areaContext.area,
                                            nextAreaStop.id,
                                          )
                                        }
                                      >
                                        Add after:{" "}
                                        {displayStopPosition(nextAreaStop)}
                                      </button>
                                    ) : null}
                                  </div>
                                ) : null}
                                {onRemoveAreaVisitStop ? (
                                  <div className="timeline-area-member-tools">
                                    {areaContext.stops
                                      .filter(
                                        (areaStop, index) =>
                                          index === 0 ||
                                          index ===
                                            areaContext.stops.length - 1,
                                      )
                                      .map((areaStop) => (
                                        <button
                                          type="button"
                                          className="timeline-tool-button"
                                          key={areaStop.id}
                                          disabled={
                                            areaContext.stops.length <= 3 ||
                                            savingAreaActionKey ===
                                              `remove:${areaContext.area.id}:${areaStop.id}`
                                          }
                                          onClick={() =>
                                            void removeStopFromArea(
                                              areaContext.area,
                                              areaStop.id,
                                            )
                                          }
                                        >
                                          Remove {displayStopPosition(areaStop)}
                                        </button>
                                      ))}
                                  </div>
                                ) : null}
                                {onDeleteAreaVisit ? (
                                  <div className="timeline-area-delete-tools">
                                    <button
                                      type="button"
                                      className="timeline-tool-button danger"
                                      disabled={
                                        savingAreaActionKey ===
                                        `delete:${areaContext.area.id}`
                                      }
                                      onClick={() =>
                                        void deleteArea(areaContext.area)
                                      }
                                    >
                                      Delete area
                                    </button>
                                  </div>
                                ) : null}
                                {areaEditError ? (
                                  <p className="error">{areaEditError}</p>
                                ) : null}
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                        <section
                          className={`timeline-stop ${
                            state.selectedStopId === stop.id ? "active" : ""
                          } ${timelineBranch.stopClassName} ${
                            isAreaSelectionMode ? "area-selection-mode" : ""
                          } ${isAreaStopSelected ? "area-selected" : ""} ${
                            isAreaSelectionMode && !canSelectForArea
                              ? "area-selection-disabled"
                              : ""
                          }`}
                          data-day-id={day.id}
                          data-stop-id={stop.id}
                          ref={(element) => {
                            activeStopRefs.current[stop.id] = element;
                          }}
                          tabIndex={canSelectTimelineStop() ? 0 : -1}
                          onFocus={() => {
                            if (
                              !isAreaSelectionMode &&
                              canSelectTimelineStop()
                            ) {
                              onStateChange(
                                selectStoryStop(state, stop.id, day.id),
                              );
                            }
                          }}
                          onKeyDown={(event) =>
                            handleTimelineKey(event, stop.id, day.id)
                          }
                        >
                          <span
                            className="timeline-branch-lane"
                            aria-hidden="true"
                          />
                          <div className="timeline-stop-card">
                            <div className="timeline-stop-heading">
                              <button
                                type="button"
                                className="timeline-stop-button"
                                disabled={
                                  isAreaSelectionMode
                                    ? !canSelectForArea
                                    : !canSelectTimelineStop()
                                }
                                onClick={() => {
                                  if (isAreaSelectionMode) {
                                    toggleAreaSelectionStop(day, stop);
                                  } else {
                                    onStateChange(
                                      selectStoryStop(state, stop.id, day.id),
                                    );
                                  }
                                }}
                              >
                                <span>
                                  <span className="timeline-stop-number">
                                    {displayStopPosition(stop)}
                                  </span>
                                  <span className="timeline-stop-title">
                                    {displayStopTitle(stop)}
                                  </span>
                                </span>
                                <time
                                  className="timeline-stop-time"
                                  dateTime={stop.startsAt}
                                >
                                  {formatTimelineStopTime(
                                    stop.startsAt,
                                    stop.startsAtLocal ?? null,
                                    timezoneId,
                                  )}
                                </time>
                                <small>
                                  {stop.mediaCount} photos ·{" "}
                                  {stop.contributorCount} travelers
                                </small>
                              </button>
                              <div className="timeline-stop-actions">
                                {isAreaSelectionMode ? (
                                  <button
                                    type="button"
                                    className="timeline-tool-button"
                                    disabled={!canSelectForArea}
                                    aria-pressed={isAreaStopSelected}
                                    onClick={() =>
                                      toggleAreaSelectionStop(day, stop)
                                    }
                                  >
                                    {isAreaStopSelected ? "Selected" : "Select"}
                                  </button>
                                ) : null}
                                {canEditStop ? (
                                  <button
                                    type="button"
                                    className="timeline-icon-button"
                                    aria-expanded={isEditingTools}
                                    aria-label={
                                      isEditingTools
                                        ? `Close editing tools for ${displayStopTitle(stop)}`
                                        : `Edit ${displayStopTitle(stop)}`
                                    }
                                    title={isEditingTools ? "Done" : "Edit"}
                                    onClick={() => {
                                      const nextStopId = isEditingTools
                                        ? null
                                        : stop.id;
                                      setEditToolsStopId(nextStopId);
                                      setEditingStopId(null);
                                      setStopTitleDraft("");
                                      setRenameStopError("");
                                      setMergeStopError("");
                                      setMergePickerStopId(null);
                                      setPendingMergeKey(null);
                                      setSplitStopId(null);
                                      setSplitStopError("");
                                      setPendingSplitKey(null);
                                      setEditingNoteKey(
                                        nextStopId ? `stop:${stop.id}` : null,
                                      );
                                      setNoteDraft(
                                        nextStopId ? (stop.note ?? "") : "",
                                      );
                                      setNoteError("");
                                    }}
                                  >
                                    <TimelineActionIcon
                                      name={isEditingTools ? "check" : "edit"}
                                    />
                                  </button>
                                ) : null}
                                <button
                                  type="button"
                                  className="timeline-icon-button timeline-map-button"
                                  aria-label={`View ${displayStopTitle(stop)} on map`}
                                  title="View on map"
                                  onClick={() =>
                                    focusTimelineStopOnMap(stop.id, day.id)
                                  }
                                >
                                  <StoryHeaderIcon action="map" />
                                </button>
                              </div>
                            </div>
                            {stop.note && !isEditingTools ? (
                              <p className="timeline-note-preview">
                                {stop.note}
                              </p>
                            ) : null}
                            {isEditingTools ? (
                              <div className="timeline-stop-edit-panel">
                                <div className="timeline-edit-context">
                                  <strong>{displayStopTitle(stop)}</strong>
                                  {onRenameStop && editingStopId !== stop.id ? (
                                    <button
                                      type="button"
                                      className="timeline-tool-button"
                                      aria-label={`Rename ${displayStopTitle(stop)}`}
                                      title="Rename"
                                      onClick={() => startRenamingStop(stop)}
                                    >
                                      <TimelineActionIcon name="edit" />
                                    </button>
                                  ) : null}
                                </div>
                                {editingStopId === stop.id ? (
                                  <form
                                    className="timeline-stop-rename"
                                    onSubmit={(event) => {
                                      event.preventDefault();
                                      void saveStopTitle(stop.id);
                                    }}
                                  >
                                    <label>
                                      Stop name
                                      <input
                                        autoFocus
                                        value={stopTitleDraft}
                                        onChange={(event) =>
                                          setStopTitleDraft(event.target.value)
                                        }
                                        onKeyDown={(event) =>
                                          event.stopPropagation()
                                        }
                                        maxLength={255}
                                        required
                                      />
                                    </label>
                                    <div className="timeline-inline-actions">
                                      <button
                                        type="submit"
                                        className="timeline-icon-button"
                                        aria-label="Save stop name"
                                        title="Save"
                                        disabled={
                                          savingStopId === stop.id ||
                                          !stopTitleDraft.trim()
                                        }
                                      >
                                        <TimelineActionIcon name="check" />
                                      </button>
                                      <button
                                        type="button"
                                        className="timeline-icon-button"
                                        aria-label="Cancel renaming"
                                        title="Cancel"
                                        onClick={() => {
                                          setEditingStopId(null);
                                          setStopTitleDraft("");
                                          setRenameStopError("");
                                        }}
                                      >
                                        <TimelineActionIcon name="x" />
                                      </button>
                                    </div>
                                    {renameStopError ? (
                                      <p className="error">{renameStopError}</p>
                                    ) : null}
                                  </form>
                                ) : null}
                                {onSetStopNote &&
                                editingNoteKey === `stop:${stop.id}` ? (
                                  <form
                                    className="timeline-note-form"
                                    onSubmit={(event) => {
                                      event.preventDefault();
                                      void saveTimelineNote(
                                        "stop",
                                        stop.id,
                                        `stop:${stop.id}`,
                                      );
                                    }}
                                  >
                                    <label>
                                      Stop note
                                      <textarea
                                        value={noteDraft}
                                        onChange={(event) =>
                                          setNoteDraft(event.target.value)
                                        }
                                        maxLength={2000}
                                        rows={3}
                                      />
                                    </label>
                                    <div className="timeline-inline-actions">
                                      <button
                                        type="submit"
                                        className="timeline-icon-button"
                                        aria-label="Save stop note"
                                        title="Save note"
                                        disabled={
                                          savingNoteKey === `stop:${stop.id}`
                                        }
                                      >
                                        <TimelineActionIcon name="check" />
                                      </button>
                                      <button
                                        type="button"
                                        className="timeline-icon-button"
                                        aria-label="Cancel note editing"
                                        title="Cancel"
                                        onClick={() => {
                                          setEditingNoteKey(null);
                                          setNoteDraft("");
                                          setNoteError("");
                                        }}
                                      >
                                        <TimelineActionIcon name="x" />
                                      </button>
                                    </div>
                                    {noteError ? (
                                      <p className="error">{noteError}</p>
                                    ) : null}
                                  </form>
                                ) : null}
                                {(onMergeStops && mergeCandidates.length > 0) ||
                                (onSplitStop && stopMedia.length > 1) ? (
                                  <div className="timeline-structure-tools">
                                    {onMergeStops &&
                                    mergeCandidates.length > 0 ? (
                                      <button
                                        type="button"
                                        className="timeline-tool-button"
                                        aria-label={
                                          mergePickerStopId === stop.id
                                            ? "Cancel merge"
                                            : "Merge with another stop"
                                        }
                                        title={
                                          mergePickerStopId === stop.id
                                            ? "Cancel merge"
                                            : "Merge"
                                        }
                                        onClick={() => {
                                          const nextMergeSourceId =
                                            mergePickerStopId === stop.id
                                              ? null
                                              : stop.id;
                                          setMergePickerStopId(
                                            nextMergeSourceId,
                                          );
                                          setPendingMergeKey(null);
                                          setMergeStopError("");
                                          if (nextMergeSourceId) {
                                            setSplitStopId(null);
                                            setSplitStopError("");
                                          }
                                        }}
                                      >
                                        {mergePickerStopId === stop.id
                                          ? "Cancel merge"
                                          : "Merge"}
                                      </button>
                                    ) : null}
                                    {onSplitStop && stopMedia.length > 1 ? (
                                      <button
                                        type="button"
                                        className="timeline-tool-button"
                                        aria-label={
                                          splitStopId === stop.id
                                            ? "Cancel split"
                                            : "Split stop"
                                        }
                                        title={
                                          splitStopId === stop.id
                                            ? "Cancel split"
                                            : "Split stop"
                                        }
                                        onClick={() => {
                                          setSplitStopId(
                                            splitStopId === stop.id
                                              ? null
                                              : stop.id,
                                          );
                                          setSplitStopError("");
                                          setPendingSplitKey(null);
                                        }}
                                      >
                                        {splitStopId === stop.id
                                          ? "Cancel split"
                                          : "Split"}
                                      </button>
                                    ) : null}
                                    {pendingMergeKey ? (
                                      <p className="timeline-stop-edit-hint">
                                        Click the same stop again to confirm.
                                      </p>
                                    ) : null}
                                    {mergeStopError ? (
                                      <p className="error">{mergeStopError}</p>
                                    ) : null}
                                  </div>
                                ) : null}
                                {canMergeHere && mergeSourceStop ? (
                                  <div className="timeline-merge-target">
                                    <p>
                                      Merge{" "}
                                      {displayStopPosition(mergeSourceStop)}{" "}
                                      into {displayStopPosition(stop)}
                                    </p>
                                    <div className="timeline-inline-actions">
                                      <button
                                        type="button"
                                        className={
                                          isPendingMergeHere
                                            ? "timeline-tool-button pending"
                                            : "timeline-tool-button"
                                        }
                                        disabled={
                                          mergeHereKey !== null &&
                                          mergingStopKey === mergeHereKey
                                        }
                                        onClick={() =>
                                          void mergeTimelineStop(
                                            mergeSourceStop.id,
                                            stop.id,
                                            day.id,
                                          )
                                        }
                                      >
                                        {isPendingMergeHere
                                          ? "Confirm merge"
                                          : "Merge here"}
                                      </button>
                                      <button
                                        type="button"
                                        className="timeline-tool-button"
                                        onClick={() => {
                                          setMergePickerStopId(null);
                                          setPendingMergeKey(null);
                                          setMergeStopError("");
                                        }}
                                      >
                                        Cancel
                                      </button>
                                    </div>
                                  </div>
                                ) : null}
                                {onMergeStops &&
                                mergePickerStopId === stop.id &&
                                mergeCandidates.length > 0 ? (
                                  <div className="timeline-stop-merge-picker">
                                    <p>Merge {displayStopTitle(stop)} with:</p>
                                    <div className="timeline-stop-merge-options">
                                      {mergeCandidates.map((candidate) => {
                                        const mergeKey = `${candidate.id}:${stop.id}`;
                                        const pending =
                                          pendingMergeKey === mergeKey;
                                        return (
                                          <button
                                            type="button"
                                            className={
                                              pending
                                                ? "timeline-tool-button pending"
                                                : "timeline-tool-button"
                                            }
                                            key={candidate.id}
                                            disabled={
                                              mergingStopKey === mergeKey
                                            }
                                            onClick={() =>
                                              void mergeTimelineStop(
                                                candidate.id,
                                                stop.id,
                                                day.id,
                                              )
                                            }
                                          >
                                            {pending
                                              ? `Confirm ${candidate.displayPosition}`
                                              : candidate.displayPosition}
                                          </button>
                                        );
                                      })}
                                    </div>
                                  </div>
                                ) : null}
                                {onSplitStop &&
                                stopMedia.length > 1 &&
                                splitStopId === stop.id ? (
                                  <div className="timeline-stop-split">
                                    <div className="timeline-stop-split-panel">
                                      <p>
                                        Choose the photo boundary where this
                                        stop should split.
                                      </p>
                                      <div className="timeline-split-boundary-row">
                                        {stopMedia.map((media, index) => {
                                          const splitKey = `${stop.id}:${media.id}`;
                                          const isPendingSplit =
                                            pendingSplitKey === splitKey;
                                          return (
                                            <Fragment key={media.id}>
                                              <div className="timeline-split-photo">
                                                {media.thumbnailUrl ? (
                                                  <img
                                                    src={media.thumbnailUrl}
                                                    alt={media.filename ?? ""}
                                                    loading="lazy"
                                                  />
                                                ) : (
                                                  <span>
                                                    {media.contributor
                                                      .slice(0, 1)
                                                      .toUpperCase()}
                                                  </span>
                                                )}
                                                <small>
                                                  {formatTimelineStopTime(
                                                    media.capturedAt ??
                                                      stop.endsAt,
                                                    media.capturedAtLocal ??
                                                      null,
                                                    timezoneId,
                                                  )}
                                                </small>
                                              </div>
                                              {index < stopMedia.length - 1 ? (
                                                <button
                                                  type="button"
                                                  className={
                                                    isPendingSplit
                                                      ? "timeline-split-boundary pending"
                                                      : "timeline-split-boundary"
                                                  }
                                                  aria-label={`Split after photo ${index + 1}`}
                                                  title="Split here"
                                                  disabled={
                                                    splittingStopKey ===
                                                    splitKey
                                                  }
                                                  onClick={() =>
                                                    void splitStopAfterMedia(
                                                      stop.id,
                                                      media.id,
                                                      day.id,
                                                    )
                                                  }
                                                >
                                                  {isPendingSplit
                                                    ? "Confirm"
                                                    : "Split"}
                                                </button>
                                              ) : null}
                                            </Fragment>
                                          );
                                        })}
                                      </div>
                                      {splitStopError ? (
                                        <p className="error">
                                          {splitStopError}
                                        </p>
                                      ) : null}
                                    </div>
                                  </div>
                                ) : null}
                              </div>
                            ) : null}
                          </div>
                        </section>
                      </div>
                    );
                  })}
                </article>
              );
            })}
          </div>
        </section>
      </aside>
      {isPhotoRollVisible ? (
        <div
          className="photo-roll-modal"
          role="dialog"
          aria-modal="true"
          aria-label="Browse photos by stop"
        >
          <button
            className="photo-roll-backdrop"
            type="button"
            aria-label="Close photo browser"
            onClick={closePhotoRoll}
          />
          <div className="photo-roll-panel">
            <div className="photo-roll-toolbar">
              <div>
                <p className="eyebrow">Photos</p>
                <h3>
                  {activeDay
                    ? `${storyDayLabel(activeDay)} photos`
                    : "Trip photos"}
                </h3>
                <span>{photoRollPhotoCount} photos grouped by stop</span>
              </div>
              <button
                type="button"
                className="modal-icon-button"
                aria-label="Close photo browser"
                title="Close"
                onClick={closePhotoRoll}
              >
                <TimelineActionIcon name="x" />
              </button>
            </div>
            <div className="story-photo-roll" aria-label="Photos by stop">
              {photoRollDays.length === 0 ? (
                <p>
                  {loadingPhotoProjectionKey
                    ? "Loading photos..."
                    : "No photos found."}
                </p>
              ) : null}
              {photoRollDays.map(({ day, stops }) => (
                <div className="story-photo-roll-day" key={day.id}>
                  {!activeDay ? (
                    <strong className="story-photo-roll-day-title">
                      {storyDayLabel(day)}
                    </strong>
                  ) : null}
                  {stops.map(({ stop, photos }) => {
                    const dayPhotos = stops.flatMap(
                      (section) => section.photos,
                    );
                    return (
                      <section className="story-photo-stop-grid" key={stop.id}>
                        <div className="story-photo-stop-heading">
                          <strong>{displayStopTitle(stop)}</strong>
                          <span>{photos.length} photos</span>
                        </div>
                        <div className="story-photo-tiles">
                          {photos.map((photo) => (
                            <button
                              type="button"
                              key={photo.id}
                              aria-label={`Open photo from ${displayStopTitle(stop)}`}
                              onClick={() =>
                                openPhotoRollPhoto(photo.id, dayPhotos)
                              }
                            >
                              {(photo.thumbnailUrl ?? photo.imageUrl) ? (
                                <img
                                  src={
                                    photo.thumbnailUrl ?? photo.imageUrl ?? ""
                                  }
                                  alt={photo.filename ?? "Trip photo"}
                                  loading="lazy"
                                />
                              ) : (
                                <span>{photo.contributor.slice(0, 1)}</span>
                              )}
                            </button>
                          ))}
                        </div>
                      </section>
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : null}
      <PhotoBrowser
        photos={browserPhotos}
        selectedPhotoId={galleryMediaId}
        timezoneId={timezoneId}
        onClose={() => {
          setGalleryMediaId(null);
          setGalleryPhotoIds(null);
          setGalleryScopedPhotos(null);
        }}
        onSelect={(photoId) => {
          const next = filteredModel.media.find((item) => item.id === photoId);
          if (next) {
            onStateChange(
              selectStoryMedia(
                state,
                next.id,
                next.momentId,
                next.stopId,
                next.dayId,
              ),
            );
          }
          setGalleryMediaId(photoId);
        }}
      />
    </div>
  );
}

function galleryPhotoFromStoryMedia(
  item: StoryMediaPoint,
  contextLabel?: string | null,
): GalleryPhoto {
  return {
    id: item.id,
    imageUrl: item.previewUrl ?? item.thumbnailUrl,
    thumbnailUrl: item.thumbnailUrl,
    filename: item.filename,
    contributor: item.contributor,
    capturedAt: item.capturedAt,
    contextLabel,
  };
}

function galleryPhotoFromStoryPhoto(
  item: StoryPhotoProjectionPhotoResponse,
  contextLabel?: string | null,
): GalleryPhoto {
  return {
    id: item.id,
    imageUrl: item.previewUrl ?? item.thumbnailUrl ?? null,
    thumbnailUrl: item.thumbnailUrl ?? null,
    filename: item.filename ?? null,
    contributor: item.contributor,
    capturedAt: item.capturedAt ?? null,
    contextLabel,
  };
}

function galleryPhotoFromMediaItem(item: MediaItemResponse): GalleryPhoto {
  return {
    id: item.id,
    imageUrl: item.preview?.downloadUrl ?? item.thumbnail?.downloadUrl ?? null,
    thumbnailUrl: item.thumbnail?.downloadUrl ?? null,
    filename: item.filename,
    contributor: item.contributor,
    capturedAt: item.capturedAt ?? null,
  };
}

function PhotoBrowser({
  photos,
  selectedPhotoId,
  timezoneId,
  onClose,
  onSelect,
}: {
  photos: GalleryPhoto[];
  selectedPhotoId: string | null;
  timezoneId?: string;
  onClose: () => void;
  onSelect: (photoId: string) => void;
}) {
  const selectedIndex = photos.findIndex(
    (photo) => photo.id === selectedPhotoId,
  );
  const selectedPhoto = selectedIndex >= 0 ? photos[selectedIndex] : null;
  const hasMultiple = photos.length > 1;

  const moveBy = useCallback(
    (delta: number) => {
      if (!selectedPhoto || photos.length === 0) {
        return;
      }
      const nextIndex = (selectedIndex + delta + photos.length) % photos.length;
      onSelect(photos[nextIndex].id);
    },
    [onSelect, photos, selectedIndex, selectedPhoto],
  );

  useEffect(() => {
    if (!selectedPhoto) {
      return;
    }
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      } else if (event.key === "ArrowLeft") {
        moveBy(-1);
      } else if (event.key === "ArrowRight") {
        moveBy(1);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [moveBy, onClose, selectedPhoto]);

  if (!selectedPhoto) {
    return null;
  }

  return (
    <div
      className="photo-browser"
      role="dialog"
      aria-modal="true"
      aria-label="Photo browser"
    >
      <button
        className="photo-browser-backdrop"
        type="button"
        aria-label="Close photo browser"
        onClick={onClose}
      />
      <div className="photo-browser-panel">
        <div className="photo-browser-toolbar">
          <div>
            <strong>
              {selectedPhoto.contributor} ·{" "}
              {formatDate(selectedPhoto.capturedAt, timezoneId)}
            </strong>
          </div>
          <button
            type="button"
            className="modal-icon-button"
            aria-label="Close photo browser"
            title="Close"
            onClick={onClose}
          >
            <TimelineActionIcon name="x" />
          </button>
        </div>
        <div className="photo-browser-stage">
          {hasMultiple ? (
            <button
              className="photo-browser-nav previous"
              type="button"
              aria-label="Previous photo"
              onClick={() => moveBy(-1)}
            >
              ‹
            </button>
          ) : null}
          {selectedPhoto.imageUrl ? (
            <img
              src={selectedPhoto.imageUrl}
              alt={selectedPhoto.filename ?? "Trip photo"}
            />
          ) : (
            <div className="photo-browser-missing">Preview unavailable</div>
          )}
          {selectedPhoto.contextLabel ? (
            <div className="photo-browser-caption">
              <span>{selectedPhoto.contextLabel}</span>
            </div>
          ) : null}
          {hasMultiple ? (
            <button
              className="photo-browser-nav next"
              type="button"
              aria-label="Next photo"
              onClick={() => moveBy(1)}
            >
              ›
            </button>
          ) : null}
        </div>
        <div className="photo-browser-footer">
          <span>
            {selectedIndex + 1} / {photos.length}
          </span>
          <div className="photo-browser-strip" aria-label="Photos">
            {photos.map((photo) => (
              <button
                className={photo.id === selectedPhoto.id ? "active" : ""}
                key={photo.id}
                type="button"
                aria-label={photo.filename ?? "Trip photo"}
                onClick={() => onSelect(photo.id)}
              >
                {(photo.thumbnailUrl ?? photo.imageUrl) ? (
                  <img
                    src={photo.thumbnailUrl ?? photo.imageUrl ?? ""}
                    alt=""
                    loading="lazy"
                  />
                ) : (
                  <span>{photo.contributor.slice(0, 1)}</span>
                )}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function storyViewLabel(viewMode: ViewMode): string {
  switch (viewMode) {
    case "DAY":
      return "Day";
    case "STOP":
      return "Stops";
    case "MOMENT":
      return "Photos";
    case "PLAYBACK":
      return "Time";
    case "TRIP_OVERVIEW":
      return "All";
  }
}

function TimelineActionIcon({ name }: { name: "check" | "edit" | "x" }) {
  if (name === "check") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="m5 12 4 4 10-10" />
      </svg>
    );
  }

  if (name === "edit") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M4 20h4.5L19 9.5 14.5 5 4 15.5V20Z" />
        <path d="m13 6 5 5" />
      </svg>
    );
  }

  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M6 6 18 18" />
      <path d="m18 6-12 12" />
    </svg>
  );
}

const storyDayColors = ["#e87856", "#8467b7", "#2fa7a2", "#d1a13d", "#4b7cc4"];

function storyDayColorMap(
  model: ReturnType<typeof buildStoryModel>,
): Map<string, string> {
  const dayIds = Array.from(
    new Set([
      ...model.stops.map((stop) => stop.dayId),
      ...model.media.map((item) => item.dayId),
      ...model.legs.map((leg) => leg.dayId),
    ]),
  );
  return new Map(
    dayIds.map((dayId, index) => [
      dayId,
      storyDayColors[index % storyDayColors.length],
    ]),
  );
}

function syncStoryMapMarkerSelection(
  markers: Marker[],
  selectedDayId: string | null,
  selectedStopId: string | null,
  selectedAreaId: string | null = null,
) {
  let selectedMarkerAnchor: HTMLElement | null = null;
  for (const marker of markers) {
    const markerAnchor = marker.getElement();
    const dayMarker = markerAnchor.querySelector(".photo-day-marker");
    const stopMarker = markerAnchor.querySelector(".photo-stop-marker");
    const areaMarker = markerAnchor.querySelector(".photo-area-marker");
    const isSelected =
      (dayMarker !== null && markerAnchor.dataset.dayId === selectedDayId) ||
      (stopMarker !== null && markerAnchor.dataset.stopId === selectedStopId) ||
      (areaMarker !== null && markerAnchor.dataset.areaId === selectedAreaId);
    markerAnchor.classList.toggle("selected", isSelected);
    markerAnchor.style.zIndex = isSelected ? "30" : "";
    dayMarker?.classList.toggle("active", isSelected);
    stopMarker?.classList.toggle("active", isSelected);
    areaMarker?.classList.toggle("active", isSelected);
    if (isSelected) {
      selectedMarkerAnchor = markerAnchor;
    }
  }
  if (selectedMarkerAnchor?.parentElement) {
    selectedMarkerAnchor.parentElement.appendChild(selectedMarkerAnchor);
  }
}

function StoryMapCanvas({
  model,
  state,
  areaVisitsByDay,
  expandedAreaId,
  activeDayLabel,
  canOpenActiveDayPhotos,
  onOpenActiveDayPhotos,
  onStateChange,
  onExpandedAreaChange,
  onDayMarkerClick,
  onStopMarkerClick,
  reducedMotion,
}: {
  model: ReturnType<typeof buildStoryModel>;
  state: StoryMapState;
  areaVisitsByDay: Record<string, AreaVisitsResponse>;
  expandedAreaId: string | null;
  activeDayLabel: string | null;
  canOpenActiveDayPhotos?: boolean;
  onOpenActiveDayPhotos?: () => void;
  onStateChange: (state: StoryMapState) => void;
  onExpandedAreaChange: (areaId: string | null) => void;
  onDayMarkerClick: (dayId: string) => void;
  onStopMarkerClick: (stopId: string, dayId: string) => void;
  reducedMotion: boolean;
}) {
  const mapNode = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const selectedMarkers = useRef<Marker[]>([]);
  const stopPhotoMarkers = useRef<Marker[]>([]);
  const previousFocusRef = useRef<{
    selectedStopId: string | null;
    viewMode: ViewMode;
  }>({ selectedStopId: null, viewMode: "TRIP_OVERVIEW" });
  const stateRef = useRef(state);
  const selectedAreaIdRef = useRef<string | null>(null);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const dayColorMap = useMemo(() => storyDayColorMap(model), [model]);
  const areaMembershipByStopId = useMemo(
    () => areaMembershipMap(areaVisitsByDay),
    [areaVisitsByDay],
  );
  const selectedAreaId = state.selectedStopId
    ? (areaMembershipByStopId.get(state.selectedStopId)?.area.id ?? null)
    : null;
  useEffect(() => {
    selectedAreaIdRef.current = selectedAreaId;
  }, [selectedAreaId]);
  const activeMapAreaVisits =
    state.selectedDayId && ["STOP", "MOMENT"].includes(state.viewMode)
      ? (areaVisitsByDay[state.selectedDayId] ?? null)
      : null;
  const visibleStopIdSet = useMemo(() => {
    if (!["STOP", "MOMENT"].includes(state.viewMode) || !state.selectedDayId) {
      return null;
    }
    const visibleStopIds = new Set<string>();
    for (const stop of model.stops) {
      if (stop.dayId !== state.selectedDayId) {
        continue;
      }
      const areaMembership = areaMembershipByStopId.get(stop.id);
      if (!areaMembership || areaMembership.area.id === expandedAreaId) {
        visibleStopIds.add(stop.id);
      }
    }
    return visibleStopIds;
  }, [
    areaMembershipByStopId,
    expandedAreaId,
    model.stops,
    state.selectedDayId,
    state.viewMode,
  ]);
  const stopDisplayCoordinates = useMemo(
    () => stopDisplayCoordinateMap(model),
    [model],
  );
  const routeCollection = useMemo(
    () =>
      storyRouteCollection(
        model,
        dayColorMap,
        state,
        areaVisitsByDay,
        expandedAreaId,
        stopDisplayCoordinates,
      ),
    [
      areaVisitsByDay,
      dayColorMap,
      expandedAreaId,
      model,
      state,
      stopDisplayCoordinates,
    ],
  );
  const stopCollection = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: model.stops
        .filter((stop) => !visibleStopIdSet || visibleStopIdSet.has(stop.id))
        .map((stop) => {
          const coordinates = stopDisplayCoordinates.get(stop.id) ?? null;
          return coordinates
            ? {
                type: "Feature" as const,
                id: stop.id,
                properties: {
                  id: stop.id,
                  dayId: stop.dayId,
                  dayColor: dayColorMap.get(stop.dayId) ?? storyDayColors[0],
                  label: stop.label,
                },
                geometry: {
                  type: "Point" as const,
                  coordinates,
                },
              }
            : null;
        })
        .filter((feature) => feature !== null),
    }),
    [dayColorMap, model.stops, stopDisplayCoordinates, visibleStopIdSet],
  );
  const mediaCollection = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: model.media
        .filter(
          (item) =>
            item.coordinates &&
            (!visibleStopIdSet || visibleStopIdSet.has(item.stopId)),
        )
        .map((item) => ({
          type: "Feature" as const,
          id: item.id,
          properties: {
            id: item.id,
            dayId: item.dayId,
            dayColor: dayColorMap.get(item.dayId) ?? storyDayColors[0],
            stopId: item.stopId,
            momentId: item.momentId,
            contributorMemberId: item.contributorMemberId,
            selected: item.id === state.selectedMediaId,
          },
          geometry: {
            type: "Point" as const,
            coordinates: item.coordinates as [number, number],
          },
        })),
    }),
    [dayColorMap, model.media, state.selectedMediaId, visibleStopIdSet],
  );
  const areaCollection = useMemo(
    () =>
      areaVisitCollection(
        areaVisitsByDay,
        stopDisplayCoordinates,
        state,
        expandedAreaId,
      ),
    [areaVisitsByDay, expandedAreaId, state, stopDisplayCoordinates],
  );
  const hasMapData =
    routeCollection.features.length > 0 ||
    stopCollection.features.length > 0 ||
    mediaCollection.features.length > 0;
  const mapDataRef = useRef({
    areaCollection,
    mediaCollection,
    routeCollection,
    stopCollection,
  });

  useEffect(() => {
    mapDataRef.current = {
      areaCollection,
      mediaCollection,
      routeCollection,
      stopCollection,
    };
  }, [areaCollection, mediaCollection, routeCollection, stopCollection]);
  const canReturnToDayMode =
    Boolean(state.selectedDayId) &&
    !["TRIP_OVERVIEW", "DAY"].includes(state.viewMode);
  const dayMarkerData = useMemo(
    () =>
      Array.from(new Set(model.stops.map((stop) => stop.dayId)))
        .map((dayId) => {
          const dayStops = model.stops.filter((stop) => stop.dayId === dayId);
          const dayMedia = model.media.filter((item) => item.dayId === dayId);
          const coordinates = centerOfCoordinates([
            ...dayStops
              .map((stop) => stopDisplayCoordinates.get(stop.id) ?? null)
              .filter((coordinate) => coordinate !== null),
            ...dayMedia
              .filter((item) => item.coordinates)
              .map((item) => item.coordinates as [number, number]),
          ]);
          const featuredMedia =
            dayMedia.find((item) => item.thumbnailUrl) ?? dayMedia[0] ?? null;
          const firstStop = dayStops[0] ?? null;
          const day = model.days.find((item) => item.id === dayId) ?? null;
          return {
            dayId,
            label: firstStop ? storyDayDateLabel(day) : "Day",
            coordinates,
            featuredMedia,
            color: dayColorMap.get(dayId) ?? storyDayColors[0],
          };
        })
        .filter((item) => item.coordinates),
    [dayColorMap, model.days, model.media, model.stops, stopDisplayCoordinates],
  );
  const stopMarkerData = useMemo(
    () =>
      model.stops
        .filter(
          (stop) =>
            !["STOP", "MOMENT"].includes(state.viewMode) ||
            !state.selectedDayId ||
            stop.dayId === state.selectedDayId,
        )
        .filter((stop) => !visibleStopIdSet || visibleStopIdSet.has(stop.id))
        .map((stop) => {
          const coordinates = stopDisplayCoordinates.get(stop.id) ?? null;
          const stopMedia = model.media.filter(
            (item) => item.stopId === stop.id,
          );
          const featuredMedia =
            stopMedia.find((item) => item.thumbnailUrl) ?? stopMedia[0] ?? null;
          return {
            stop,
            coordinates,
            featuredMedia,
            count: stopMedia.length,
            flowLabel: stop.displayPosition,
            flowTone: stop.displayPosition === "1" ? "start" : "step",
            color: dayColorMap.get(stop.dayId) ?? storyDayColors[0],
          };
        }),
    [
      dayColorMap,
      model.media,
      model.stops,
      state.selectedDayId,
      state.viewMode,
      stopDisplayCoordinates,
      visibleStopIdSet,
    ],
  );
  const areaMarkerData = useMemo(() => {
    if (!activeMapAreaVisits) {
      return [];
    }
    return activeMapAreaVisits.areas
      .filter((area) => area.id !== expandedAreaId)
      .map((area) => {
        const areaStopIds = new Set(area.stops.map((stop) => stop.id));
        const coordinates = centerOfCoordinates(
          area.stops
            .map((stop) => stopDisplayCoordinates.get(stop.id) ?? null)
            .filter((coordinate) => coordinate !== null),
        );
        const areaMedia = model.media.filter((item) =>
          areaStopIds.has(item.stopId),
        );
        const featuredMedia =
          areaMedia.find((item) => item.thumbnailUrl) ?? areaMedia[0] ?? null;
        const firstStopId =
          model.stops.find(
            (stop) =>
              stop.dayId === activeMapAreaVisits.dayId &&
              areaStopIds.has(stop.id),
          )?.id ?? area.stops[0]?.id;
        return {
          area,
          coordinates,
          featuredMedia,
          firstStopId,
          color:
            dayColorMap.get(activeMapAreaVisits.dayId) ?? storyDayColors[0],
          selected: area.id === selectedAreaId,
          stopCount: area.stops.length,
        };
      })
      .filter((item) => item.coordinates && item.firstStopId);
  }, [
    activeMapAreaVisits,
    dayColorMap,
    expandedAreaId,
    model.media,
    model.stops,
    selectedAreaId,
    stopDisplayCoordinates,
  ]);
  const orderedDayMarkerData = useMemo(
    () =>
      [...dayMarkerData].sort((left, right) => {
        const leftSelected = left.dayId === state.selectedDayId;
        const rightSelected = right.dayId === state.selectedDayId;
        return Number(leftSelected) - Number(rightSelected);
      }),
    [dayMarkerData, state.selectedDayId],
  );
  const orderedStopMarkerData = useMemo(
    () =>
      [...stopMarkerData].sort((left, right) => {
        const leftSelected = left.stop.id === state.selectedStopId;
        const rightSelected = right.stop.id === state.selectedStopId;
        return Number(leftSelected) - Number(rightSelected);
      }),
    [state.selectedStopId, stopMarkerData],
  );
  const orderedAreaMarkerData = useMemo(
    () =>
      [...areaMarkerData].sort(
        (left, right) => Number(left.selected) - Number(right.selected),
      ),
    [areaMarkerData],
  );
  const showDayMarkers =
    state.viewMode === "DAY" || state.viewMode === "TRIP_OVERVIEW";

  useEffect(() => {
    if (!["STOP", "MOMENT"].includes(state.viewMode) || !state.selectedDayId) {
      onExpandedAreaChange(null);
      return;
    }
    if (!expandedAreaId) {
      return;
    }
    if (!state.selectedStopId) {
      return;
    }
    const selectedStopArea =
      areaMembershipByStopId.get(state.selectedStopId)?.area.id ?? null;
    if (selectedStopArea !== expandedAreaId) {
      onExpandedAreaChange(null);
    }
  }, [
    areaMembershipByStopId,
    expandedAreaId,
    onExpandedAreaChange,
    state.selectedDayId,
    state.selectedStopId,
    state.viewMode,
  ]);

  useEffect(() => {
    if (!mapNode.current || mapRef.current) {
      return;
    }
    const map = new maplibregl.Map({
      container: mapNode.current,
      style: configuredMapStyle(),
      center: [0, 0],
      zoom: 1,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    const emptyFeatureCollection = {
      type: "FeatureCollection" as const,
      features: [],
    };

    map.on("dragstart", () =>
      onStateChange(markUserControlled(stateRef.current)),
    );
    map.on("load", () => {
      map.addSource("trip-routes", {
        type: "geojson",
        data: emptyFeatureCollection,
      });
      map.addSource("trip-stops", {
        type: "geojson",
        data: emptyFeatureCollection,
      });
      map.addSource("trip-media", {
        type: "geojson",
        data: emptyFeatureCollection,
        cluster: true,
        clusterRadius: 36,
      });
      map.addSource("trip-areas", {
        type: "geojson",
        data: emptyFeatureCollection,
      });
      (map.getSource("trip-routes") as GeoJSONSource | undefined)?.setData(
        mapDataRef.current.routeCollection,
      );
      (map.getSource("trip-stops") as GeoJSONSource | undefined)?.setData(
        mapDataRef.current.stopCollection,
      );
      (map.getSource("trip-media") as GeoJSONSource | undefined)?.setData(
        mapDataRef.current.mediaCollection,
      );
      (map.getSource("trip-areas") as GeoJSONSource | undefined)?.setData(
        mapDataRef.current.areaCollection,
      );
      for (const { id, level, expandedOpacity, defaultOpacity } of [
        {
          id: "area-visits-glow-outer",
          level: "outer",
          expandedOpacity: 0.05,
          defaultOpacity: 0.025,
        },
        {
          id: "area-visits-glow-middle",
          level: "middle",
          expandedOpacity: 0.1,
          defaultOpacity: 0.045,
        },
        {
          id: "area-visits-glow-core",
          level: "core",
          expandedOpacity: 0.18,
          defaultOpacity: 0.08,
        },
      ] as const) {
        map.addLayer({
          id,
          type: "fill",
          source: "trip-areas",
          filter: ["==", ["get", "glowLevel"], level],
          paint: {
            "fill-color": "#267563",
            "fill-opacity": [
              "case",
              ["==", ["get", "expanded"], true],
              expandedOpacity,
              defaultOpacity,
            ],
          },
        });
      }
      map.addLayer({
        id: "routes-confirmed",
        type: "line",
        source: "trip-routes",
        filter: ["!=", ["get", "routeSource"], "photo_inferred"],
        paint: {
          "line-color": ["get", "dayColor"],
          "line-width": ["case", ["==", ["get", "isForked"], true], 2.4, 4],
          "line-opacity": 0.9,
        },
      });
      map.addLayer({
        id: "routes-inferred",
        type: "line",
        source: "trip-routes",
        filter: ["==", ["get", "routeSource"], "photo_inferred"],
        paint: {
          "line-color": ["get", "dayColor"],
          "line-width": ["case", ["==", ["get", "isForked"], true], 2, 3.4],
          "line-dasharray": [2, 2],
          "line-opacity": 0.82,
        },
      });
      map.addLayer({
        id: "media-clusters",
        type: "circle",
        source: "trip-media",
        filter: ["has", "point_count"],
        paint: {
          "circle-color": "#2f6f75",
          "circle-radius": ["step", ["get", "point_count"], 16, 20, 22, 80, 30],
          "circle-opacity": 0.82,
        },
      });
      map.addLayer({
        id: "media-unclustered",
        type: "circle",
        source: "trip-media",
        filter: ["!", ["has", "point_count"]],
        paint: {
          "circle-color": [
            "case",
            ["==", ["get", "selected"], true],
            "#9f2d20",
            ["get", "dayColor"],
          ],
          "circle-radius": ["case", ["==", ["get", "selected"], true], 8, 5],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 2,
        },
      });
      map.addLayer({
        id: "stops",
        type: "circle",
        source: "trip-stops",
        paint: {
          "circle-color": [
            "case",
            ["==", ["get", "selected"], true],
            "#9f2d20",
            ["get", "dayColor"],
          ],
          "circle-radius": ["case", ["==", ["get", "selected"], true], 13, 10],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 3,
          "circle-opacity": 0,
          "circle-stroke-opacity": 0,
        },
      });
      const mediaVisibility =
        stateRef.current.viewMode === "DAY" ||
        stateRef.current.viewMode === "TRIP_OVERVIEW"
          ? "none"
          : "visible";
      for (const layerId of ["media-clusters", "media-unclustered"]) {
        map.setLayoutProperty(layerId, "visibility", mediaVisibility);
      }
      map.on("click", "stops", (event) => {
        if (stateRef.current.viewMode === "DAY") {
          return;
        }
        const feature = event.features?.[0];
        const stopId = feature?.properties?.id as string | undefined;
        const dayId = feature?.properties?.dayId as string | undefined;
        if (stopId && dayId) {
          onStateChange(selectStoryStop(stateRef.current, stopId, dayId));
        }
      });
      map.on("click", "media-unclustered", (event) => {
        if (stateRef.current.viewMode === "DAY") {
          return;
        }
        const feature = event.features?.[0];
        const mediaId = feature?.properties?.id as string | undefined;
        const momentId = feature?.properties?.momentId as string | undefined;
        const stopId = feature?.properties?.stopId as string | undefined;
        const dayId = feature?.properties?.dayId as string | undefined;
        if (mediaId && momentId && stopId && dayId) {
          onStateChange(
            selectStoryMedia(
              stateRef.current,
              mediaId,
              momentId,
              stopId,
              dayId,
            ),
          );
        }
      });
      map.on("click", (event) => {
        const clickedFeatures = map.queryRenderedFeatures(event.point, {
          layers: ["stops", "media-unclustered"],
        });
        if (clickedFeatures.length > 0) {
          return;
        }
        window.requestAnimationFrame(() =>
          syncStoryMapMarkerSelection(
            stopPhotoMarkers.current,
            stateRef.current.selectedDayId,
            stateRef.current.selectedStopId,
            selectedAreaIdRef.current,
          ),
        );
      });
    });

    return () => {
      selectedMarkers.current.forEach((marker) => marker.remove());
      selectedMarkers.current = [];
      stopPhotoMarkers.current.forEach((marker) => marker.remove());
      stopPhotoMarkers.current = [];
      map.remove();
      mapRef.current = null;
    };
  }, [onStateChange]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.isStyleLoaded()) {
      return;
    }
    (map.getSource("trip-routes") as GeoJSONSource | undefined)?.setData(
      routeCollection,
    );
    (map.getSource("trip-stops") as GeoJSONSource | undefined)?.setData(
      stopCollection,
    );
    (map.getSource("trip-media") as GeoJSONSource | undefined)?.setData(
      mediaCollection,
    );
    (map.getSource("trip-areas") as GeoJSONSource | undefined)?.setData(
      areaCollection,
    );
  }, [areaCollection, mediaCollection, routeCollection, stopCollection]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.isStyleLoaded()) {
      return;
    }
    const mediaVisibility = showDayMarkers ? "none" : "visible";
    for (const layerId of ["media-clusters", "media-unclustered"]) {
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, "visibility", mediaVisibility);
      }
    }
  }, [showDayMarkers]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    stopPhotoMarkers.current.forEach((marker) => marker.remove());
    stopPhotoMarkers.current = [];
    if (showDayMarkers) {
      for (const {
        dayId,
        label,
        coordinates,
        featuredMedia,
        color,
      } of orderedDayMarkerData) {
        if (!coordinates) {
          continue;
        }
        const markerAnchor = document.createElement("div");
        markerAnchor.className = "photo-map-marker-anchor";
        markerAnchor.dataset.dayId = dayId;
        const element = document.createElement("button");
        element.type = "button";
        element.className = "photo-day-marker";
        element.setAttribute("aria-label", `Explore stops for ${label}`);
        element.style.setProperty("--stop-color", color);
        if (featuredMedia?.thumbnailUrl) {
          const image = document.createElement("img");
          image.src = featuredMedia.thumbnailUrl;
          image.alt = "";
          image.loading = "lazy";
          element.appendChild(image);
        } else {
          const fallback = document.createElement("span");
          fallback.textContent = label.replace("Day ", "");
          element.appendChild(fallback);
        }
        const title = document.createElement("strong");
        title.textContent = label;
        element.appendChild(title);
        element.addEventListener("click", (event) => {
          event.stopPropagation();
          onDayMarkerClick(dayId);
        });
        markerAnchor.appendChild(element);
        stopPhotoMarkers.current.push(
          new maplibregl.Marker({ anchor: "center", element: markerAnchor })
            .setLngLat(coordinates)
            .addTo(map),
        );
      }
      syncStoryMapMarkerSelection(
        stopPhotoMarkers.current,
        state.selectedDayId,
        state.selectedStopId,
        selectedAreaId,
      );
      return () => {
        stopPhotoMarkers.current.forEach((marker) => marker.remove());
        stopPhotoMarkers.current = [];
      };
    }
    for (const {
      area,
      coordinates,
      featuredMedia,
      firstStopId,
      color,
      stopCount,
    } of orderedAreaMarkerData) {
      if (!coordinates || !firstStopId) {
        continue;
      }
      const title = area.title ?? `Area ${area.sortOrder}`;
      const markerAnchor = document.createElement("div");
      markerAnchor.className = "photo-map-marker-anchor";
      markerAnchor.dataset.dayId = area.dayId;
      markerAnchor.dataset.areaId = area.id;
      const element = document.createElement("button");
      element.type = "button";
      element.className = "photo-area-marker";
      element.setAttribute(
        "aria-label",
        `Show ${stopCount} stops in ${title}, area ${area.sortOrder}`,
      );
      element.style.setProperty("--stop-color", color);
      const bubble = document.createElement("span");
      bubble.className = "photo-area-marker-image";
      if (featuredMedia?.thumbnailUrl) {
        const image = document.createElement("img");
        image.src = featuredMedia.thumbnailUrl;
        image.alt = "";
        image.loading = "lazy";
        bubble.appendChild(image);
        const orderBadge = document.createElement("small");
        orderBadge.className = "photo-area-marker-order";
        orderBadge.textContent = `A${area.sortOrder}`;
        bubble.appendChild(orderBadge);
      } else {
        const fallback = document.createElement("span");
        fallback.textContent = `A${area.sortOrder}`;
        bubble.appendChild(fallback);
      }
      const label = document.createElement("strong");
      label.className = "photo-area-marker-label";
      label.textContent = `${title} · ${stopCount} stop${
        stopCount === 1 ? "" : "s"
      }`;
      element.appendChild(bubble);
      element.appendChild(label);
      element.addEventListener("click", (event) => {
        event.stopPropagation();
        onExpandedAreaChange(area.id);
        onStateChange(
          selectStoryStop(stateRef.current, firstStopId, area.dayId),
        );
      });
      markerAnchor.appendChild(element);
      stopPhotoMarkers.current.push(
        new maplibregl.Marker({ anchor: "center", element: markerAnchor })
          .setLngLat(coordinates)
          .addTo(map),
      );
    }
    for (const {
      stop,
      coordinates,
      featuredMedia,
      flowLabel,
      flowTone,
      color,
    } of orderedStopMarkerData) {
      if (!coordinates) {
        continue;
      }
      const markerAnchor = document.createElement("div");
      markerAnchor.className = "photo-map-marker-anchor";
      markerAnchor.dataset.dayId = stop.dayId;
      markerAnchor.dataset.stopId = stop.id;
      const element = document.createElement("button");
      element.type = "button";
      element.className = "photo-stop-marker";
      element.setAttribute(
        "aria-label",
        `Open photos for ${stop.label}, ${flowLabel} stop`,
      );
      element.style.setProperty("--stop-color", color);
      const bubble = document.createElement("span");
      bubble.className = "photo-stop-marker-image";
      const mediaFrame = document.createElement("span");
      mediaFrame.className = "photo-stop-marker-frame";
      if (featuredMedia?.thumbnailUrl) {
        const image = document.createElement("img");
        image.src = featuredMedia.thumbnailUrl;
        image.alt = "";
        image.loading = "lazy";
        mediaFrame.appendChild(image);
      } else {
        const fallback = document.createElement("span");
        fallback.textContent = stop.displayPosition;
        mediaFrame.appendChild(fallback);
      }
      bubble.appendChild(mediaFrame);
      const sequence = document.createElement("small");
      sequence.className = `photo-stop-sequence ${flowTone}`;
      sequence.textContent = flowLabel;
      bubble.appendChild(sequence);
      const label = document.createElement("strong");
      label.className = "photo-stop-marker-label";
      label.textContent = stop.label;
      element.appendChild(bubble);
      element.appendChild(label);
      element.addEventListener("click", (event) => {
        event.stopPropagation();
        onStopMarkerClick(stop.id, stop.dayId);
      });
      markerAnchor.appendChild(element);
      stopPhotoMarkers.current.push(
        new maplibregl.Marker({ anchor: "center", element: markerAnchor })
          .setLngLat(coordinates)
          .addTo(map),
      );
    }
    syncStoryMapMarkerSelection(
      stopPhotoMarkers.current,
      state.selectedDayId,
      state.selectedStopId,
      selectedAreaId,
    );
    return () => {
      stopPhotoMarkers.current.forEach((marker) => marker.remove());
      stopPhotoMarkers.current = [];
    };
  }, [
    onDayMarkerClick,
    onExpandedAreaChange,
    onStopMarkerClick,
    orderedDayMarkerData,
    orderedAreaMarkerData,
    orderedStopMarkerData,
    selectedAreaId,
    showDayMarkers,
    state.selectedDayId,
    state.selectedStopId,
  ]);

  useEffect(() => {
    syncStoryMapMarkerSelection(
      stopPhotoMarkers.current,
      state.selectedDayId,
      state.selectedStopId,
      selectedAreaId,
    );
  }, [selectedAreaId, state.selectedDayId, state.selectedStopId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    selectedMarkers.current.forEach((marker) => marker.remove());
    selectedMarkers.current = [];
    if (showDayMarkers) {
      return;
    }
    const selectedMedia = model.media
      .filter(
        (item) =>
          item.id === state.selectedMediaId ||
          item.momentId === state.selectedMomentId,
      )
      .slice(0, 5);
    for (const item of selectedMedia) {
      if (!item.coordinates) {
        continue;
      }
      const element = document.createElement("div");
      element.className = "selected-photo-marker";
      element.textContent = item.contributor.slice(0, 1).toUpperCase();
      selectedMarkers.current.push(
        new maplibregl.Marker({ element })
          .setLngLat(item.coordinates)
          .addTo(map),
      );
    }
  }, [
    model.media,
    model.stops,
    showDayMarkers,
    state.selectedMediaId,
    state.selectedMomentId,
    state.selectedStopId,
  ]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || state.mapControlMode !== "STORY_CONTROLLED") {
      return;
    }
    const coordinates = focusCoordinates(
      model,
      state,
      stopDisplayCoordinates,
      areaVisitsByDay,
      expandedAreaId,
    );
    if (coordinates.length === 0) {
      return;
    }
    if (state.viewMode === "STOP" && state.selectedStopId) {
      const previousFocus = previousFocusRef.current;
      previousFocusRef.current = {
        selectedStopId: state.selectedStopId,
        viewMode: state.viewMode,
      };
      if (previousFocus.viewMode !== "STOP") {
        const dayCoordinates = dayStopCoordinates(
          model,
          state.selectedDayId,
          stopDisplayCoordinates,
        );
        if (dayCoordinates.length > 1) {
          map.fitBounds(boundsForCoordinates(dayCoordinates), {
            padding: 56,
            maxZoom: 14,
            duration: reducedMotion ? 0 : 700,
          });
          return;
        }
      }
      const targetZoom = stopSelectionZoom(
        model,
        state.selectedDayId,
        coordinates[0],
        stopDisplayCoordinates,
      );
      if (
        previousFocus.viewMode === "STOP" &&
        previousFocus.selectedStopId &&
        previousFocus.selectedStopId !== state.selectedStopId
      ) {
        map.easeTo({
          center: coordinates[0],
          zoom: Math.max(map.getZoom(), targetZoom),
          duration: reducedMotion ? 0 : 360,
        });
        return;
      }
      map.easeTo({
        center: coordinates[0],
        zoom: Math.max(map.getZoom(), targetZoom),
        duration: reducedMotion ? 0 : 360,
      });
      return;
    }
    previousFocusRef.current = {
      selectedStopId: state.selectedStopId,
      viewMode: state.viewMode,
    };
    if (coordinates.length === 1) {
      map.easeTo({
        center: coordinates[0],
        zoom: 14,
        duration: reducedMotion ? 0 : 600,
      });
    } else {
      map.fitBounds(boundsForCoordinates(coordinates), {
        padding: 56,
        maxZoom: 14,
        duration: reducedMotion ? 0 : 700,
      });
    }
  }, [
    areaVisitsByDay,
    expandedAreaId,
    model,
    reducedMotion,
    state,
    stopDisplayCoordinates,
  ]);

  return (
    <div
      className={`story-map-shell ${
        hasConfiguredMapStyle() ? "configured-map-shell" : "local-map-shell"
      }`}
    >
      <div className="story-map" ref={mapNode} aria-hidden="true" />
      {activeDayLabel && ["STOP", "MOMENT"].includes(state.viewMode) ? (
        <div className="map-active-day" aria-live="polite">
          {canReturnToDayMode && state.selectedDayId ? (
            <button
              type="button"
              className="map-active-day-back"
              aria-label="Back to day view"
              title="Back to day view"
              onClick={() =>
                onStateChange(
                  selectStoryDay(state, state.selectedDayId as string),
                )
              }
            >
              <svg aria-hidden="true" viewBox="0 0 24 24">
                <path d="m15 18-6-6 6-6" />
              </svg>
            </button>
          ) : null}
          <div>
            <strong>{activeDayLabel}</strong>
          </div>
          {canOpenActiveDayPhotos && onOpenActiveDayPhotos ? (
            <button
              type="button"
              className="map-active-day-photos"
              aria-label="Browse selected day photos"
              title="Browse selected day photos"
              onClick={onOpenActiveDayPhotos}
            >
              <StoryHeaderIcon action="photos" />
            </button>
          ) : null}
        </div>
      ) : null}
      {!hasMapData ? (
        <div className="map-empty-state">
          <strong>No mapped stops yet</strong>
          <span>
            Add GPS photos and refresh the story to draw stops and routes.
          </span>
        </div>
      ) : null}
    </div>
  );
}

type AreaVisitFeature = {
  type: "Feature";
  id: string;
  properties: {
    id: string;
    dayId: string;
    title: string;
    selected: boolean;
    expanded: boolean;
    glowLevel: "outer" | "middle" | "core";
  };
  geometry: {
    type: "Polygon";
    coordinates: number[][][];
  };
};

function areaMembershipMap(
  areaVisitsByDay: Record<string, AreaVisitsResponse>,
): Map<string, { area: AreaVisitResponse; dayId: string }> {
  const memberships = new Map<
    string,
    { area: AreaVisitResponse; dayId: string }
  >();
  for (const [dayId, areaVisits] of Object.entries(areaVisitsByDay)) {
    for (const area of areaVisits.areas) {
      for (const stop of area.stops) {
        memberships.set(stop.id, { area, dayId });
      }
    }
  }
  return memberships;
}

function storyRouteCollection(
  model: ReturnType<typeof buildStoryModel>,
  dayColorMap: Map<string, string>,
  state: StoryMapState,
  areaVisitsByDay: Record<string, AreaVisitsResponse>,
  expandedAreaId: string | null,
  stopCoordinates: Map<string, [number, number]>,
) {
  const activeStopMode =
    ["STOP", "MOMENT"].includes(state.viewMode) && state.selectedDayId;
  const activeAreaVisits = activeStopMode
    ? (areaVisitsByDay[state.selectedDayId ?? ""] ?? null)
    : null;
  const collapsedAreaByStopId = new Map<string, AreaVisitResponse>();
  const collapsedAreaCenters = new Map<string, [number, number]>();

  for (const area of activeAreaVisits?.areas ?? []) {
    if (area.id === expandedAreaId) {
      continue;
    }
    const coordinates = area.stops
      .map((stop) => stopCoordinates.get(stop.id) ?? null)
      .filter((coordinate) => coordinate !== null);
    const center = centerOfCoordinates(coordinates);
    if (!center) {
      continue;
    }
    collapsedAreaCenters.set(area.id, center);
    for (const stop of area.stops) {
      collapsedAreaByStopId.set(stop.id, area);
    }
  }

  return {
    type: "FeatureCollection" as const,
    features: model.legs
      .filter(
        (leg) =>
          leg.geometry &&
          (!activeStopMode ||
            !state.selectedDayId ||
            leg.dayId === state.selectedDayId),
      )
      .map((leg) => {
        if (!leg.geometry) {
          return null;
        }
        const fromArea = collapsedAreaByStopId.get(leg.fromStopId) ?? null;
        const toArea = collapsedAreaByStopId.get(leg.toStopId) ?? null;
        if (fromArea && toArea && fromArea.id === toArea.id) {
          return null;
        }
        const fromCoordinate =
          (fromArea
            ? collapsedAreaCenters.get(fromArea.id)
            : stopCoordinates.get(leg.fromStopId)) ??
          lngLatCoordinate(leg.geometry.coordinates[0]);
        const toCoordinate =
          (toArea
            ? collapsedAreaCenters.get(toArea.id)
            : stopCoordinates.get(leg.toStopId)) ??
          lngLatCoordinate(
            leg.geometry.coordinates[leg.geometry.coordinates.length - 1],
          );
        if (!fromCoordinate || !toCoordinate) {
          return null;
        }
        const isAreaEdge = Boolean(fromArea || toArea);
        return {
          type: "Feature" as const,
          id: isAreaEdge
            ? `${leg.id}:area:${fromArea?.id ?? leg.fromStopId}:${
                toArea?.id ?? leg.toStopId
              }`
            : leg.id,
          properties: {
            id: leg.id,
            dayId: leg.dayId,
            dayColor: dayColorMap.get(leg.dayId) ?? storyDayColors[0],
            routeSource: isAreaEdge ? "area_collapsed" : leg.routeSource,
            isForked: isAreaEdge ? false : leg.isForked,
          },
          geometry: {
            type: "LineString" as const,
            coordinates: isAreaEdge
              ? [fromCoordinate, toCoordinate]
              : leg.geometry.coordinates,
          },
        };
      })
      .filter((feature) => feature !== null),
  };
}

function areaVisitCollection(
  areaVisitsByDay: Record<string, AreaVisitsResponse>,
  stopCoordinates: Map<string, [number, number]>,
  state: StoryMapState,
  expandedAreaId: string | null,
) {
  const activeDayId =
    state.viewMode === "TRIP_OVERVIEW" ? null : state.selectedDayId;
  const showExpandedAreaOnly = ["STOP", "MOMENT"].includes(state.viewMode);
  const features: AreaVisitFeature[] = [];
  for (const [dayId, areaVisits] of Object.entries(areaVisitsByDay)) {
    if (activeDayId && dayId !== activeDayId) {
      continue;
    }
    for (const area of areaVisits.areas) {
      if (showExpandedAreaOnly && area.id !== expandedAreaId) {
        continue;
      }
      const coordinates = area.stops
        .map((stop) => stopCoordinates.get(stop.id) ?? null)
        .filter((coordinate) => coordinate !== null);
      for (const { glowLevel, scale } of [
        { glowLevel: "outer", scale: 1.9 },
        { glowLevel: "middle", scale: 1.42 },
        { glowLevel: "core", scale: 1 },
      ] as const) {
        const polygon = areaPolygonForCoordinates(coordinates, scale);
        if (!polygon) {
          continue;
        }
        features.push({
          type: "Feature",
          id: `${area.id}:${glowLevel}`,
          properties: {
            id: area.id,
            dayId,
            title: area.title ?? `Area ${area.sortOrder}`,
            selected: area.stops.some(
              (stop) => stop.id === state.selectedStopId,
            ),
            expanded: area.id === expandedAreaId,
            glowLevel,
          },
          geometry: {
            type: "Polygon",
            coordinates: [polygon],
          },
        });
      }
    }
  }
  return {
    type: "FeatureCollection" as const,
    features,
  };
}

function areaPolygonForCoordinates(
  coordinates: [number, number][],
  scale = 1,
): number[][] | null {
  if (coordinates.length === 0) {
    return null;
  }
  const longitudes = coordinates.map((coordinate) => coordinate[0]);
  const latitudes = coordinates.map((coordinate) => coordinate[1]);
  const minLongitude = Math.min(...longitudes);
  const maxLongitude = Math.max(...longitudes);
  const minLatitude = Math.min(...latitudes);
  const maxLatitude = Math.max(...latitudes);
  const centerLongitude = (minLongitude + maxLongitude) / 2;
  const centerLatitude = (minLatitude + maxLatitude) / 2;
  const latitudeScale = Math.max(
    Math.cos(degreesToRadians(centerLatitude)),
    0.25,
  );
  const latitudeRadius = Math.max((maxLatitude - minLatitude) / 2, 0.0011);
  const longitudeRadius = Math.max(
    (maxLongitude - minLongitude) / 2,
    0.0011 / latitudeScale,
  );
  const basePaddedLatitudeRadius =
    latitudeRadius + Math.max(latitudeRadius * 0.45, 0.0006);
  const basePaddedLongitudeRadius =
    longitudeRadius + Math.max(longitudeRadius * 0.45, 0.0006 / latitudeScale);
  const paddedLatitudeRadius = basePaddedLatitudeRadius * scale;
  const paddedLongitudeRadius = basePaddedLongitudeRadius * scale;
  const ring = Array.from({ length: 24 }, (_, index) => {
    const angle = (index / 24) * Math.PI * 2;
    return [
      centerLongitude + Math.cos(angle) * paddedLongitudeRadius,
      centerLatitude + Math.sin(angle) * paddedLatitudeRadius,
    ];
  });
  return [...ring, ring[0]];
}

function centerOfCoordinates(
  coordinates: [number, number][],
): [number, number] | null {
  if (coordinates.length === 0) {
    return null;
  }
  const longitudes = coordinates.map((coordinate) => coordinate[0]);
  const latitudes = coordinates.map((coordinate) => coordinate[1]);
  return [
    (Math.min(...longitudes) + Math.max(...longitudes)) / 2,
    (Math.min(...latitudes) + Math.max(...latitudes)) / 2,
  ];
}

function displayStopCoordinate(
  stop: StoryStopPoint,
  legs: StoryLegLine[],
): [number, number] | null {
  for (const leg of legs) {
    const coordinates = leg.geometry?.coordinates ?? [];
    if (coordinates.length === 0) {
      continue;
    }
    if (leg.toStopId === stop.id) {
      return lngLatCoordinate(coordinates[coordinates.length - 1]);
    }
    if (leg.fromStopId === stop.id) {
      return lngLatCoordinate(coordinates[0]);
    }
  }
  return stop.coordinates;
}

function stopDisplayCoordinateMap(
  model: ReturnType<typeof buildStoryModel>,
): Map<string, [number, number]> {
  const coordinates = new Map<string, [number, number]>();
  for (const stop of model.stops) {
    const coordinate =
      stop.coordinates ?? displayStopCoordinate(stop, model.legs);
    if (coordinate) {
      coordinates.set(stop.id, coordinate);
    }
  }
  return coordinates;
}

function lngLatCoordinate(
  coordinate: number[] | undefined,
): [number, number] | null {
  if (
    !coordinate ||
    coordinate.length < 2 ||
    typeof coordinate[0] !== "number" ||
    typeof coordinate[1] !== "number"
  ) {
    return null;
  }
  return [coordinate[0], coordinate[1]];
}

function focusCoordinates(
  model: ReturnType<typeof buildStoryModel>,
  state: StoryMapState,
  stopCoordinates: Map<string, [number, number]>,
  areaVisitsByDay: Record<string, AreaVisitsResponse>,
  expandedAreaId: string | null,
): [number, number][] {
  if (state.viewMode === "TRIP_OVERVIEW" || state.viewMode === "DAY") {
    return [
      ...model.stops
        .map((item) => stopCoordinates.get(item.id) ?? null)
        .filter((coordinate) => coordinate !== null),
      ...model.media
        .filter((item) => item.coordinates)
        .map((item) => item.coordinates as [number, number]),
    ];
  }
  if (state.selectedMediaId) {
    return model.media
      .filter((item) => item.id === state.selectedMediaId && item.coordinates)
      .map((item) => item.coordinates as [number, number]);
  }
  if (state.selectedMomentId) {
    return model.media
      .filter(
        (item) => item.momentId === state.selectedMomentId && item.coordinates,
      )
      .map((item) => item.coordinates as [number, number]);
  }
  if (state.selectedStopId) {
    const selectedCollapsedAreaCoordinate = collapsedAreaCoordinateForStop(
      state.selectedStopId,
      state.selectedDayId,
      areaVisitsByDay,
      expandedAreaId,
      stopCoordinates,
    );
    if (selectedCollapsedAreaCoordinate) {
      return [selectedCollapsedAreaCoordinate];
    }
    const stop = model.stops.find((item) => item.id === state.selectedStopId);
    const stopCoordinate = stop ? (stopCoordinates.get(stop.id) ?? null) : null;
    if (stopCoordinate) {
      return [stopCoordinate];
    }
    return model.media
      .filter(
        (item) => item.stopId === state.selectedStopId && item.coordinates,
      )
      .slice(0, 1)
      .map((item) => item.coordinates as [number, number]);
  }
  if (state.selectedDayId) {
    return [
      ...model.stops
        .filter((item) => item.dayId === state.selectedDayId)
        .map((item) => stopCoordinates.get(item.id) ?? null)
        .filter((coordinate) => coordinate !== null),
      ...model.media
        .filter(
          (item) => item.dayId === state.selectedDayId && item.coordinates,
        )
        .map((item) => item.coordinates as [number, number]),
    ];
  }
  return [
    ...model.stops
      .map((item) => stopCoordinates.get(item.id) ?? null)
      .filter((coordinate) => coordinate !== null),
    ...model.media
      .filter((item) => item.coordinates)
      .map((item) => item.coordinates as [number, number]),
  ];
}

function collapsedAreaCoordinateForStop(
  stopId: string,
  dayId: string | null,
  areaVisitsByDay: Record<string, AreaVisitsResponse>,
  expandedAreaId: string | null,
  stopCoordinates: Map<string, [number, number]>,
): [number, number] | null {
  if (!dayId) {
    return null;
  }
  for (const area of areaVisitsByDay[dayId]?.areas ?? []) {
    if (area.id === expandedAreaId) {
      continue;
    }
    if (!area.stops.some((stop) => stop.id === stopId)) {
      continue;
    }
    return centerOfCoordinates(
      area.stops
        .map((stop) => stopCoordinates.get(stop.id) ?? null)
        .filter((coordinate) => coordinate !== null),
    );
  }
  return null;
}

function dayStopCoordinates(
  model: ReturnType<typeof buildStoryModel>,
  dayId: string | null,
  stopCoordinates: Map<string, [number, number]>,
): [number, number][] {
  if (!dayId) {
    return [];
  }
  return model.stops
    .filter((stop) => stop.dayId === dayId)
    .map((stop) => stopCoordinates.get(stop.id) ?? null)
    .filter((coordinate) => coordinate !== null);
}

function stopSelectionZoom(
  model: ReturnType<typeof buildStoryModel>,
  dayId: string | null,
  selectedCoordinate: [number, number],
  stopCoordinates: Map<string, [number, number]>,
): number {
  const nearestDistance = dayStopCoordinates(model, dayId, stopCoordinates)
    .map((coordinate) => distanceMeters(selectedCoordinate, coordinate))
    .filter((distance) => distance > 0.5)
    .sort((left, right) => left - right)[0];
  if (typeof nearestDistance !== "number") {
    return 13.4;
  }
  if (nearestDistance < 120) {
    return 16.2;
  }
  if (nearestDistance < 250) {
    return 15.5;
  }
  if (nearestDistance < 500) {
    return 14.8;
  }
  if (nearestDistance < 900) {
    return 14.1;
  }
  return 13.4;
}

function distanceMeters(
  left: [number, number],
  right: [number, number],
): number {
  const earthRadiusMeters = 6_371_000;
  const leftLatitude = degreesToRadians(left[1]);
  const rightLatitude = degreesToRadians(right[1]);
  const latitudeDelta = degreesToRadians(right[1] - left[1]);
  const longitudeDelta = degreesToRadians(right[0] - left[0]);
  const haversine =
    Math.sin(latitudeDelta / 2) ** 2 +
    Math.cos(leftLatitude) *
      Math.cos(rightLatitude) *
      Math.sin(longitudeDelta / 2) ** 2;
  return (
    2 *
    earthRadiusMeters *
    Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine))
  );
}

function degreesToRadians(value: number): number {
  return (value * Math.PI) / 180;
}

function boundsForCoordinates(coordinates: [number, number][]): LngLatBounds {
  const bounds = new LngLatBounds(coordinates[0], coordinates[0]);
  for (const coordinate of coordinates.slice(1)) {
    bounds.extend(coordinate);
  }
  return bounds;
}

function useReducedMotion(): boolean {
  const [reducedMotion, setReducedMotion] = useState(() => {
    if (typeof window === "undefined" || !window.matchMedia) {
      return false;
    }
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  });
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) {
      return;
    }
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const listener = (event: MediaQueryListEvent) =>
      setReducedMotion(event.matches);
    query.addEventListener("change", listener);
    return () => query.removeEventListener("change", listener);
  }, []);
  return reducedMotion;
}

function useMediaQuery(queryText: string): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof window === "undefined" || !window.matchMedia) {
      return false;
    }
    return window.matchMedia(queryText).matches;
  });
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) {
      return;
    }
    const query = window.matchMedia(queryText);
    const listener = (event: MediaQueryListEvent) => setMatches(event.matches);
    query.addEventListener("change", listener);
    return () => query.removeEventListener("change", listener);
  }, [queryText]);
  return matches;
}

function TripFields({
  form,
  onChange,
}: {
  form: TripForm;
  onChange: (form: TripForm) => void;
}) {
  const timeZones = useMemo(
    () => timeZoneOptions(form.timezoneId),
    [form.timezoneId],
  );
  const validTimeZone = isSupportedTimeZone(form.timezoneId);

  function setField(field: keyof TripForm, value: string) {
    onChange({ ...form, [field]: value });
  }

  return (
    <>
      <label>
        Title
        <input
          value={form.title}
          onChange={(event) => setField("title", event.target.value)}
          required
        />
      </label>
      <label>
        Description
        <textarea
          value={form.description}
          onChange={(event) => setField("description", event.target.value)}
          rows={3}
        />
      </label>
      <div className="field-grid">
        <label>
          Start date
          <input
            type="date"
            value={form.startDate}
            onChange={(event) => setField("startDate", event.target.value)}
          />
        </label>
        <label>
          End date
          <input
            type="date"
            value={form.endDate}
            onChange={(event) => setField("endDate", event.target.value)}
          />
        </label>
      </div>
      <div className="field-grid">
        <label>
          Time zone
          <select
            value={form.timezoneId}
            onChange={(event) => setField("timezoneId", event.target.value)}
            required
          >
            {timeZones.map((timeZone) => (
              <option key={timeZone} value={timeZone}>
                {timeZone}
                {timeZone === form.timezoneId && !validTimeZone
                  ? " (invalid, choose another)"
                  : ""}
              </option>
            ))}
          </select>
          {!validTimeZone ? (
            <span className="field-hint warning">
              Choose an IANA time zone such as Asia/Seoul.
            </span>
          ) : null}
        </label>
        <label>
          Day cutoff hour
          <input
            max={23}
            min={0}
            type="number"
            value={form.dayCutoffHour}
            onChange={(event) => setField("dayCutoffHour", event.target.value)}
            required
          />
        </label>
      </div>
    </>
  );
}

function StoryAutoUpdateNotice({
  canUpdateStory,
  hasProcessingMedia,
  hasStory,
  isUpdating,
  storyUpdate,
}: {
  canUpdateStory: boolean;
  hasProcessingMedia: boolean;
  hasStory: boolean;
  isUpdating: boolean;
  storyUpdate: {
    needsUpdate: boolean;
    unassignedReadyMediaCount: number;
  } | null;
}) {
  if (isUpdating) {
    return (
      <section className="story-auto-update-notice active" aria-live="polite">
        <span className="button-spinner" aria-hidden="true" />
        <div>
          <strong>Updating story</strong>
          <small>Map and timeline are rebuilding now.</small>
        </div>
      </section>
    );
  }

  if (hasProcessingMedia) {
    return (
      <section className="story-auto-update-notice" aria-live="polite">
        <span aria-hidden="true" />
        <div>
          <strong>Preparing photos</strong>
          <small>
            Story will update automatically after processing finishes.
          </small>
        </div>
      </section>
    );
  }

  if (storyUpdate?.needsUpdate) {
    const count = storyUpdate.unassignedReadyMediaCount;
    if (!hasStory) {
      return (
        <section className="story-auto-update-notice queued" aria-live="polite">
          <span aria-hidden="true" />
          <div>
            <strong>Story setup needed</strong>
            <small>
              {canUpdateStory
                ? "Run Update Story once. Future uploads will update automatically."
                : "An organizer needs to run the first story update."}
            </small>
          </div>
        </section>
      );
    }
    return (
      <section className="story-auto-update-notice queued" aria-live="polite">
        <span aria-hidden="true" />
        <div>
          <strong>
            {count} ready photo{count === 1 ? "" : "s"} waiting
          </strong>
          <small>Story update is queued automatically.</small>
        </div>
      </section>
    );
  }

  return null;
}

function UploadFileList({
  files,
  progress,
  onCancel,
  onRetry,
}: {
  files: UploadFileResponse[];
  progress: Record<string, UploadProgress>;
  onCancel: (file: UploadFileResponse) => void;
  onRetry: (file: UploadFileResponse, selectedFile?: File) => void;
}) {
  const visibleFiles = files
    .map((file) => {
      const itemProgress = progress[file.id];
      const status = itemProgress?.status ?? file.state;
      return { file, itemProgress, status };
    })
    .filter(({ file, itemProgress, status }) =>
      shouldShowUploadStatus(file, itemProgress, status),
    );

  if (visibleFiles.length === 0) {
    return null;
  }

  const failedCount = visibleFiles.filter(
    ({ file, itemProgress, status }) =>
      status === "failed" || Boolean(itemProgress?.error || file.errorMessage),
  ).length;
  const activeCount = visibleFiles.length - failedCount;
  const loaded = visibleFiles.reduce(
    (total, { itemProgress }) => total + (itemProgress?.loaded ?? 0),
    0,
  );
  const total = visibleFiles.reduce(
    (sum, { file, itemProgress }) =>
      sum + (itemProgress?.total ?? file.byteSize ?? 0),
    0,
  );
  const percent = total > 0 ? Math.round((loaded / total) * 100) : 0;

  return (
    <section className="upload-status" aria-label="Upload status">
      <div className="upload-summary">
        <strong>
          {activeCount > 0
            ? `Uploading ${activeCount}`
            : "Uploads need attention"}
        </strong>
        <small>
          {failedCount > 0 ? `Failed ${failedCount}` : `${percent}% complete`}
        </small>
      </div>
      {activeCount > 0 ? (
        <progress max={100} value={percent} aria-label="Upload progress" />
      ) : null}
      <div className="upload-list" role="list">
        {visibleFiles.map(({ file, itemProgress, status }) => {
          const loaded = itemProgress?.loaded ?? 0;
          const total = itemProgress?.total ?? file.byteSize ?? 0;
          const percent = total > 0 ? Math.round((loaded / total) * 100) : 0;
          return (
            <div className="upload-row" key={file.id} role="listitem">
              <div>
                <strong>{file.filename}</strong>
                <small>
                  {status} · {file.mimeType ?? "unknown type"}
                </small>
              </div>
              <progress
                max={100}
                value={percent}
                aria-label={`${file.filename} progress`}
              />
              <div className="button-row">
                {["uploading", "pending", "registered", "failed"].includes(
                  status,
                ) ? (
                  <button type="button" onClick={() => onCancel(file)}>
                    Cancel
                  </button>
                ) : null}
                {file.grant &&
                (status === "failed" ||
                  file.state === "registered" ||
                  file.state === "transferring") ? (
                  <label className="file-action">
                    Retry
                    <input
                      accept=".jpg,.jpeg,.heic,image/jpeg,image/heic,image/heif"
                      type="file"
                      onChange={(event) => {
                        const selectedFile = event.target.files?.[0];
                        if (selectedFile) {
                          onRetry(file, selectedFile);
                        }
                        event.target.value = "";
                      }}
                    />
                  </label>
                ) : null}
              </div>
              {itemProgress?.error ? (
                <p className="error">{itemProgress.error}</p>
              ) : file.errorMessage ? (
                <p className="error">{file.errorMessage}</p>
              ) : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function shouldShowUploadStatus(
  file: UploadFileResponse,
  itemProgress: UploadProgress | undefined,
  status: string,
) {
  return (
    Boolean(itemProgress?.error || file.errorMessage) ||
    ["pending", "uploading", "registered", "transferring", "failed"].includes(
      status,
    )
  );
}

function InvitationList({
  invitations,
  onRevoke,
}: {
  invitations: InvitationResponse[];
  onRevoke: (invitation: InvitationResponse) => void;
}) {
  if (invitations.length === 0) {
    return <p>No invitations yet.</p>;
  }
  return (
    <div className="simple-list" role="list">
      {invitations.map((invitation) => (
        <div className="simple-row" key={invitation.id} role="listitem">
          <div>
            <strong>{invitation.role}</strong>
            <small>
              {invitation.status} · {invitation.useCount}/{invitation.maxUses}{" "}
              used
            </small>
          </div>
          {invitation.status === "pending" ? (
            <button type="button" onClick={() => onRevoke(invitation)}>
              Revoke
            </button>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function MemberRoster({
  members,
  onRemove,
}: {
  members: MemberResponse[];
  onRemove: (member: MemberResponse) => void;
}) {
  if (members.length === 0) {
    return <p>No members yet.</p>;
  }
  return (
    <div className="simple-list" role="list">
      {members.map((member) => (
        <div className="simple-row" key={member.id} role="listitem">
          <div>
            <strong>{member.displayName}</strong>
            <small>
              {member.role}
              {member.isGuest ? " · guest" : ""}{" "}
              {member.removedAt ? " · removed" : ""}
            </small>
          </div>
          {!member.removedAt && member.role !== "owner" ? (
            <button type="button" onClick={() => onRemove(member)}>
              Remove
            </button>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function PublicationList({
  publications,
  onRevoke,
}: {
  publications: PublicationsListResponse | null;
  onRevoke: (id: string) => void;
}) {
  if (!publications) {
    return <p>No publication data loaded.</p>;
  }
  return (
    <div className="publication-grid">
      <div>
        <h3>Versions</h3>
        {publications.versions.length === 0 ? (
          <p>No versions yet.</p>
        ) : (
          <div className="compact-list">
            {publications.versions.map((version) => (
              <div className="compact-row" key={version.id}>
                <span>v{version.versionNumber}</span>
                <small>{version.state}</small>
                {version.errorMessage ? (
                  <small className="error">{version.errorMessage}</small>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>
      <div>
        <h3>Share links</h3>
        {publications.shareLinks.length === 0 ? (
          <p>No links yet.</p>
        ) : (
          <div className="compact-list">
            {publications.shareLinks.map((link) => (
              <div className="compact-row" key={link.id}>
                <span>{link.status}</span>
                <small>
                  {link.storyVersionId ? "version assigned" : "publishing"}
                </small>
                <small>URL hidden after creation</small>
                {link.status === "active" ? (
                  <button type="button" onClick={() => onRevoke(link.id)}>
                    Revoke
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function PublicStoryViewer({
  token,
  initialView = "story",
}: {
  token: string;
  initialView?: "story" | "slideshow";
}) {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [story, setStory] = useState<PublicStoryResponse | null>(null);
  const [error, setError] = useState("");
  const [storyState, setStoryState] = useState<StoryMapState>(() =>
    initialStoryMapState(),
  );
  const [mobilePane, setMobilePane] = useState<StoryMobilePane>("map");
  const [publicView, setPublicView] = useState<"story" | "slideshow">(
    initialView,
  );

  useEffect(() => {
    let cancelled = false;
    api
      .publicStory(token)
      .then((result) => {
        if (!cancelled) {
          setStory(result);
          setError("");
        }
      })
      .catch((reason) => {
        if (!cancelled) {
          setError(messageFrom(reason));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoadState("ready");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (loadState === "loading") {
    return (
      <main className="app-shell">
        <p className="eyebrow">Published story</p>
        <h1>Loading story</h1>
      </main>
    );
  }

  if (error || !story) {
    return (
      <main className="app-shell">
        <section className="panel stack">
          <p className="eyebrow">Published story</p>
          <h1>Story unavailable</h1>
          <p>{error || "This story is not available."}</p>
        </section>
      </main>
    );
  }

  const trip = story.trip as {
    title?: unknown;
    description?: unknown;
    timezoneId?: unknown;
  };
  const title = typeof trip.title === "string" ? trip.title : "Trip story";
  const description =
    typeof trip.description === "string" ? trip.description : null;
  const timezoneId =
    typeof trip.timezoneId === "string" ? trip.timezoneId : "UTC";
  const areaVisitsByDay = areaVisitsByDayRecord(story.areaVisitsByDay);
  const slideshowScenes = buildPublicStorySlideshowScenes(story);

  if (publicView === "slideshow") {
    return (
      <PublicStorySlideshow
        scenes={slideshowScenes}
        title={title}
        timezoneId={timezoneId}
        onExit={() => setPublicView("story")}
      />
    );
  }

  return (
    <main className="app-shell public-story-shell">
      <header className="app-header">
        <div className="public-story-title">
          <p className="eyebrow">TripWeave story</p>
          <h1>{title}</h1>
          <p>
            {description
              ? description
              : `Published version ${story.version.versionNumber}`}
          </p>
        </div>
        <nav className="public-story-view-toggle" aria-label="Story view">
          {(
            [
              ["map", "Map"],
              ["timeline", "Timeline"],
              ["photos", "Photos"],
            ] as Array<[StoryMobilePane, string]>
          ).map(([action, label]) => (
            <button
              type="button"
              aria-label={label}
              aria-pressed={mobilePane === action}
              className={mobilePane === action ? "active" : ""}
              key={action}
              onClick={() => setMobilePane(action)}
              title={label}
            >
              <StoryHeaderIcon action={action} />
            </button>
          ))}
          <button
            type="button"
            aria-label="Slideshow"
            aria-pressed={false}
            onClick={() => setPublicView("slideshow")}
            title="Slideshow"
          >
            <StoryHeaderIcon action="slideshow" />
          </button>
        </nav>
      </header>
      <TripStoryExplorer
        reconstruction={story.story}
        state={storyState}
        onStateChange={setStoryState}
        initialAreaVisitsByDay={areaVisitsByDay}
        mobilePane={mobilePane}
        onMobilePaneChange={setMobilePane}
        timezoneId={timezoneId}
      />
    </main>
  );
}

function PublicStorySlideshow({
  scenes,
  title,
  timezoneId,
  onExit,
}: {
  scenes: SlideshowScene[];
  title: string;
  timezoneId: string;
  onExit: () => void;
}) {
  const [requestedActiveIndex, setRequestedActiveIndex] = useState(0);
  const [isPaused, setIsPaused] = useState(false);
  const shellRef = useRef<HTMLElement | null>(null);
  const reducedMotion = useReducedMotion();
  const activeIndex =
    scenes.length > 0 ? Math.min(requestedActiveIndex, scenes.length - 1) : 0;
  const activeScene = scenes[activeIndex] ?? null;
  const activePhoto = activeScene?.type === "photo" ? activeScene.photo : null;
  const [lastMapScene, setLastMapScene] = useState<Extract<
    SlideshowScene,
    { type: "day" | "stop" }
  > | null>(() => {
    const firstMapScene = scenes.find(
      (scene) => scene.type === "day" || scene.type === "stop",
    );
    return firstMapScene?.type === "day" || firstMapScene?.type === "stop"
      ? firstMapScene
      : null;
  });
  const hasMultipleScenes = scenes.length > 1;
  const activeMapScene =
    activeScene?.type === "day" || activeScene?.type === "stop"
      ? activeScene
      : null;
  const visibleMapScene = activeMapScene ?? lastMapScene;

  useEffect(() => {
    if (!activeMapScene) {
      return;
    }
    const timeout = window.setTimeout(() => setLastMapScene(activeMapScene), 0);
    return () => window.clearTimeout(timeout);
  }, [activeMapScene]);

  const goToPrevious = useCallback(() => {
    if (!hasMultipleScenes) {
      return;
    }
    setRequestedActiveIndex((index) =>
      activeIndex === 0 ? scenes.length - 1 : Math.max(0, index - 1),
    );
  }, [activeIndex, hasMultipleScenes, scenes.length]);

  const goToNext = useCallback(() => {
    if (!hasMultipleScenes) {
      return;
    }
    setRequestedActiveIndex((index) => (index + 1) % scenes.length);
  }, [hasMultipleScenes, scenes.length]);

  useEffect(() => {
    if (isPaused || reducedMotion || !hasMultipleScenes || !activeScene) {
      return;
    }
    const timeout = window.setTimeout(goToNext, activeScene.durationMs);
    return () => window.clearTimeout(timeout);
  }, [activeScene, goToNext, hasMultipleScenes, isPaused, reducedMotion]);

  useEffect(() => {
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        goToPrevious();
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        goToNext();
      } else if (event.key === " ") {
        event.preventDefault();
        setIsPaused((value) => !value);
      } else if (event.key === "Escape") {
        onExit();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [goToNext, goToPrevious, onExit]);

  async function requestFullscreen() {
    const element = shellRef.current;
    if (!element || !element.requestFullscreen) {
      return;
    }
    try {
      await element.requestFullscreen();
    } catch {
      setIsPaused(true);
    }
  }

  return (
    <main
      className="slideshow-shell"
      ref={shellRef}
      aria-label={`${title} slideshow`}
    >
      {visibleMapScene ? <SlideshowMapScene scene={visibleMapScene} /> : null}
      {activePhoto ? (
        <SlideshowPhotoStage
          photo={activePhoto}
          title={title}
          reducedMotion={reducedMotion}
        />
      ) : !visibleMapScene ? (
        <div className="slideshow-stage">
          <div className="slideshow-empty">
            <p>No published photos are available for slideshow.</p>
          </div>
        </div>
      ) : null}
      <header className="slideshow-topbar">
        <div className="slideshow-controls" aria-label="Slideshow controls">
          <button
            type="button"
            onClick={() => setIsPaused((value) => !value)}
            disabled={!hasMultipleScenes}
            aria-label={isPaused || reducedMotion ? "Play" : "Pause"}
            title={isPaused || reducedMotion ? "Play" : "Pause"}
          >
            <SlideshowControlIcon
              action={isPaused || reducedMotion ? "play" : "pause"}
            />
          </button>
          <button
            type="button"
            onClick={() => void requestFullscreen()}
            aria-label="Full screen"
            title="Full screen"
          >
            <SlideshowControlIcon action="fullscreen" />
          </button>
          <button
            type="button"
            onClick={onExit}
            aria-label="Back to story"
            title="Back to story"
          >
            <SlideshowControlIcon action="close" />
          </button>
        </div>
      </header>
      {activeScene?.type === "day" || activeScene?.type === "stop" ? (
        <footer className="slideshow-caption map-caption">
          <div className="slideshow-caption-copy">
            <span className="slideshow-trip-title">{title}</span>
            <span className="slideshow-caption-kicker">
              {activeScene.type === "day"
                ? "Day overview"
                : activeScene.dayLabel}
            </span>
            <strong>{activeScene.title}</strong>
            <div className="slideshow-caption-meta">
              <span>{activeScene.subtitle}</span>
            </div>
          </div>
          <span className="slideshow-counter">
            {activeIndex + 1} / {scenes.length}
          </span>
        </footer>
      ) : activePhoto ? (
        <footer className="slideshow-caption">
          <div className="slideshow-caption-copy">
            <span className="slideshow-trip-title">{title}</span>
            <strong>{activePhoto.stopLabel}</strong>
            <div className="slideshow-caption-meta">
              <span>{formatDate(activePhoto.capturedAt, timezoneId)}</span>
              <span>{activePhoto.contributor}</span>
            </div>
          </div>
          <span className="slideshow-counter">
            {activeIndex + 1} / {scenes.length}
          </span>
        </footer>
      ) : null}
      {hasMultipleScenes ? (
        <>
          <button
            type="button"
            className="slideshow-nav previous"
            aria-label="Previous photo"
            onClick={goToPrevious}
          >
            {"<"}
          </button>
          <button
            type="button"
            className="slideshow-nav next"
            aria-label="Next photo"
            onClick={goToNext}
          >
            {">"}
          </button>
        </>
      ) : null}
    </main>
  );
}

function SlideshowPhotoStage({
  photo,
  title,
  reducedMotion,
}: {
  photo: SlideshowPhoto;
  title: string;
  reducedMotion: boolean;
}) {
  const [displayedPhoto, setDisplayedPhoto] = useState(photo);
  const [previousPhoto, setPreviousPhoto] = useState<SlideshowPhoto | null>(
    null,
  );
  const [isPhotoReady, setIsPhotoReady] = useState(false);
  const [shouldFadeFromMap, setShouldFadeFromMap] = useState(true);

  useEffect(() => {
    if (displayedPhoto.id === photo.id) {
      return;
    }
    const timeout = window.setTimeout(() => {
      setPreviousPhoto(reducedMotion ? null : displayedPhoto);
      setDisplayedPhoto(photo);
      setIsPhotoReady(false);
      setShouldFadeFromMap(false);
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [displayedPhoto, photo, reducedMotion]);

  useEffect(() => {
    const image = new Image();
    image.onload = () => setIsPhotoReady(true);
    image.onerror = () => setIsPhotoReady(true);
    image.src = displayedPhoto.imageUrl;
    return () => {
      image.onload = null;
      image.onerror = null;
    };
  }, [displayedPhoto]);

  useEffect(() => {
    if (!previousPhoto || !isPhotoReady || reducedMotion) {
      return;
    }
    const timeout = window.setTimeout(() => setPreviousPhoto(null), 900);
    return () => window.clearTimeout(timeout);
  }, [isPhotoReady, previousPhoto, reducedMotion]);

  return (
    <div className="slideshow-stage slideshow-photo-stage">
      {previousPhoto ? (
        <div
          aria-hidden="true"
          className="slideshow-photo-layer slideshow-photo-layer-previous"
          role="img"
          style={{ backgroundImage: `url("${previousPhoto.imageUrl}")` }}
        />
      ) : null}
      {isPhotoReady ? (
        <div
          className={`slideshow-photo-layer slideshow-photo-layer-current ${
            shouldFadeFromMap && !previousPhoto
              ? "slideshow-photo-layer-map-enter"
              : ""
          }`}
          key={displayedPhoto.id}
        >
          <div
            aria-label={displayedPhoto.filename ?? `${title} travel photo`}
            className={`slideshow-photo-frame ${
              previousPhoto ? "slideshow-photo-frame-current" : ""
            }`}
            role="img"
            style={{ backgroundImage: `url("${displayedPhoto.imageUrl}")` }}
          />
        </div>
      ) : null}
    </div>
  );
}

function SlideshowControlIcon({
  action,
}: {
  action: "play" | "pause" | "fullscreen" | "close";
}) {
  if (action === "play") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M8 5v14l11-7z" />
      </svg>
    );
  }
  if (action === "pause") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M8 5v14" />
        <path d="M16 5v14" />
      </svg>
    );
  }
  if (action === "fullscreen") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M8 4H4v4" />
        <path d="M16 4h4v4" />
        <path d="M20 16v4h-4" />
        <path d="M4 16v4h4" />
      </svg>
    );
  }
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M6 6l12 12" />
      <path d="M18 6 6 18" />
    </svg>
  );
}

function SlideshowMapScene({
  scene,
}: {
  scene: Extract<SlideshowScene, { type: "day" | "stop" }>;
}) {
  const mapNode = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markersRef = useRef<Marker[]>([]);
  const reducedMotion = useReducedMotion();
  const hasMapData = scene.stops.some((stop) => stop.coordinates);

  useEffect(() => {
    if (!mapNode.current || mapRef.current) {
      return;
    }
    const map = new maplibregl.Map({
      container: mapNode.current,
      style: configuredMapStyle(),
      center: [0, 0],
      zoom: 1,
      attributionControl: { compact: true },
      interactive: false,
    });
    mapRef.current = map;
    map.on("load", () => {
      map.addSource("slideshow-routes", {
        type: "geojson",
        data: slideshowRouteCollection([]),
      });
      map.addLayer({
        id: "slideshow-routes-line",
        type: "line",
        source: "slideshow-routes",
        paint: {
          "line-color": "#f5b35b",
          "line-opacity": 0.78,
          "line-width": 4,
        },
        layout: {
          "line-cap": "round",
          "line-join": "round",
        },
      });
    });
    return () => {
      markersRef.current.forEach((marker) => marker.remove());
      markersRef.current = [];
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    markersRef.current.forEach((marker) => marker.remove());
    markersRef.current = [];

    for (const stop of scene.stops) {
      if (!stop.coordinates) {
        continue;
      }
      const element = document.createElement("div");
      element.className =
        scene.type === "stop" && stop.id === scene.activeStopId
          ? "slideshow-map-marker active"
          : "slideshow-map-marker";
      element.textContent = String(stop.position);
      markersRef.current.push(
        new maplibregl.Marker({ element, anchor: "center" })
          .setLngLat(stop.coordinates)
          .addTo(map),
      );
    }

    const syncRoute = () => {
      const source = map.getSource("slideshow-routes") as
        GeoJSONSource | undefined;
      source?.setData(slideshowRouteCollection(scene.routes));
    };
    if (map.loaded()) {
      syncRoute();
    } else {
      map.once("load", syncRoute);
    }

    const activeStop =
      scene.type === "stop"
        ? scene.stops.find((stop) => stop.id === scene.activeStopId)
        : null;
    const focusCoordinates =
      scene.type === "stop" && activeStop?.coordinates
        ? [activeStop.coordinates]
        : scene.stops
            .map((stop) => stop.coordinates)
            .filter((coordinate) => coordinate !== null);

    if (focusCoordinates.length === 0) {
      return;
    }
    const frameId = window.requestAnimationFrame(() => {
      map.resize();
      if (focusCoordinates.length === 1) {
        map.easeTo({
          center: focusCoordinates[0],
          zoom: scene.type === "stop" ? 14.8 : 12,
          duration: reducedMotion ? 0 : 900,
        });
        return;
      }
      map.fitBounds(boundsForCoordinates(focusCoordinates), {
        padding: 120,
        maxZoom: scene.type === "stop" ? 14.8 : 12,
        duration: reducedMotion ? 0 : 1000,
      });
    });
    return () => window.cancelAnimationFrame(frameId);
  }, [reducedMotion, scene]);

  return (
    <div
      className={`slideshow-map-stage ${
        hasConfiguredMapStyle() ? "configured-map-shell" : "local-map-shell"
      }`}
    >
      <div className="slideshow-map" ref={mapNode} aria-hidden="true" />
      {!hasMapData ? (
        <div className="slideshow-map-empty">
          <p>No mapped stops are available for this scene.</p>
        </div>
      ) : null}
    </div>
  );
}

function slideshowRouteCollection(routes: SlideshowRoute[]) {
  return {
    type: "FeatureCollection" as const,
    features: routes.map((route) => ({
      type: "Feature" as const,
      id: route.id,
      properties: { id: route.id },
      geometry: {
        type: "LineString" as const,
        coordinates: route.coordinates,
      },
    })),
  };
}

function areaVisitsByDayRecord(
  value: Record<string, unknown> | undefined,
): Record<string, AreaVisitsResponse> | undefined {
  if (!value) {
    return undefined;
  }
  return Object.fromEntries(
    Object.entries(value).filter(([, areaVisits]) =>
      isAreaVisitsResponse(areaVisits),
    ),
  ) as Record<string, AreaVisitsResponse>;
}

function isAreaVisitsResponse(value: unknown): value is AreaVisitsResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as { areas?: unknown; standaloneStops?: unknown };
  return (
    Array.isArray(candidate.areas) && Array.isArray(candidate.standaloneStops)
  );
}

function StoryHeaderIcon({ action }: { action: StoryHeaderIconAction }) {
  if (action === "map" || action === "story") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M9 5 3.8 7.1v12L9 17l6 2 5.2-2.1v-12L15 7 9 5Z" />
        <path d="M9 5v12" />
        <path d="M15 7v12" />
      </svg>
    );
  }

  if (action === "photos") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M5 7.5h14v11H5z" />
        <path d="m8 15 2.5-3 2 2.2 1.5-1.7 2.2 2.5" />
        <path d="M8.5 10h.01" />
      </svg>
    );
  }

  if (action === "slideshow") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M4 6h16v11H4z" />
        <path d="M9 20h6" />
        <path d="M12 17v3" />
        <path d="m8 14 2.4-3 2 2.1 1.5-1.7 2.1 2.6" />
        <path d="M8.4 9.2h.01" />
      </svg>
    );
  }

  if (action === "upload") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M5 7.5h14v11H5z" />
        <path d="m8 15 2.5-3 2 2.2 1.5-1.7 2.2 2.5" />
        <path d="M12 4v7" />
        <path d="m9.5 6.5 2.5-2.5 2.5 2.5" />
      </svg>
    );
  }

  if (action === "share") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M12 3v12" />
        <path d="m7.5 7.5 4.5-4.5 4.5 4.5" />
        <path d="M6 11v8h12v-8" />
      </svg>
    );
  }

  if (action === "update") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M20 11a8 8 0 0 0-13.7-5.3L4 8" />
        <path d="M4 4v4h4" />
        <path d="M4 13a8 8 0 0 0 13.7 5.3L20 16" />
        <path d="M20 20v-4h-4" />
      </svg>
    );
  }

  if (action === "more") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M5 12h.01" />
        <path d="M12 12h.01" />
        <path d="M19 12h.01" />
      </svg>
    );
  }

  if (action === "manage") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M5 6h14" />
        <path d="M5 12h14" />
        <path d="M5 18h14" />
        <path d="M8 4v4" />
        <path d="M16 10v4" />
        <path d="M11 16v4" />
      </svg>
    );
  }

  if (action === "settings") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z" />
        <path d="M19 12a7.6 7.6 0 0 0-.1-1l2-1.6-2-3.5-2.5 1a7.3 7.3 0 0 0-1.8-1l-.4-2.7h-4l-.4 2.7a7.3 7.3 0 0 0-1.8 1l-2.5-1-2 3.5 2 1.6a7.6 7.6 0 0 0 0 2l-2 1.6 2 3.5 2.5-1a7.3 7.3 0 0 0 1.8 1l.4 2.7h4l.4-2.7a7.3 7.3 0 0 0 1.8-1l2.5 1 2-3.5-2-1.6c.1-.3.1-.7.1-1Z" />
      </svg>
    );
  }

  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M5 7h14" />
      <path d="M5 12h14" />
      <path d="M5 17h14" />
    </svg>
  );
}

function ReconstructionOutline({
  reconstruction,
  timezoneId,
  reviewIndex,
  onSkipReview,
  onResolveReview,
  onDismissReview,
  onAcceptClockOffset,
  onUndo,
}: {
  reconstruction: ReconstructionResponse | null;
  timezoneId: string;
  reviewIndex: number;
  onSkipReview: () => void;
  onResolveReview: (id: string) => void;
  onDismissReview: (id: string) => void;
  onAcceptClockOffset: (id: string) => void;
  onUndo: () => void;
}) {
  if (!reconstruction?.latestRun) {
    return <p>No reconstruction run yet.</p>;
  }
  const openReviewItems = reconstruction.reviewItems.filter(
    (item) => item.status === "open",
  );
  const severityCounts = openReviewItems.reduce<Record<string, number>>(
    (counts, item) => {
      counts[item.severity] = (counts[item.severity] ?? 0) + 1;
      return counts;
    },
    {},
  );
  const currentReview =
    openReviewItems.length > 0
      ? openReviewItems[reviewIndex % openReviewItems.length]
      : null;
  return (
    <div className="outline">
      <div className="summary-grid">
        <div>
          <strong>{reconstruction.latestRun.state}</strong>
          <small>{reconstruction.latestRun.algorithmVersion}</small>
        </div>
        <div>
          <strong>{String(reconstruction.latestRun.summary.days ?? 0)}</strong>
          <small>days</small>
        </div>
        <div>
          <strong>{String(reconstruction.latestRun.summary.stops ?? 0)}</strong>
          <small>stops</small>
        </div>
        <div>
          <strong>
            {String(reconstruction.latestRun.summary.reviewItems ?? 0)}
          </strong>
          <small>review items</small>
        </div>
      </div>
      <div className="review-inbox">
        <div className="section-heading">
          <div>
            <h3>Review inbox</h3>
            <p>
              {openReviewItems.length} open issue
              {openReviewItems.length === 1 ? "" : "s"} ·{" "}
              {Object.entries(severityCounts)
                .map(([severity, count]) => `${severity}: ${count}`)
                .join(", ") || "clear"}
            </p>
          </div>
          <button type="button" onClick={onUndo}>
            Undo latest edit
          </button>
        </div>
        {currentReview ? (
          <article className="review-card">
            <div>
              <strong>{currentReview.itemType}</strong>
              <small>
                {currentReview.severity} · confidence{" "}
                {currentReview.confidence ?? "unknown"} ·{" "}
                {currentReview.targetType ?? "trip"}
              </small>
            </div>
            <p>{currentReview.message}</p>
            {currentReview.itemType === "possible_clock_offset" ? (
              <dl className="compact-facts">
                <div>
                  <dt>Offset</dt>
                  <dd>{String(currentReview.payload.offsetSeconds ?? "?")}s</dd>
                </div>
                <div>
                  <dt>Support</dt>
                  <dd>{String(currentReview.payload.supportCount ?? "?")}</dd>
                </div>
                <div>
                  <dt>Dispersion</dt>
                  <dd>
                    {String(currentReview.payload.dispersionSeconds ?? "?")}s
                  </dd>
                </div>
              </dl>
            ) : null}
            {currentReview.itemType === "possible_area_visit" ? (
              <dl className="compact-facts">
                <div>
                  <dt>Stops</dt>
                  <dd>{String(currentReview.payload.stopCount ?? "?")}</dd>
                </div>
                <div>
                  <dt>Threshold</dt>
                  <dd>{String(currentReview.payload.threshold ?? "?")}</dd>
                </div>
                <div>
                  <dt>Diameter</dt>
                  <dd>
                    {Math.round(
                      Number(currentReview.payload.diameterMeters ?? 0),
                    )}
                    m
                  </dd>
                </div>
              </dl>
            ) : null}
            <div className="button-row">
              {currentReview.itemType === "possible_clock_offset" ? (
                <button
                  type="button"
                  onClick={() => onAcceptClockOffset(currentReview.id)}
                >
                  Accept offset
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => onResolveReview(currentReview.id)}
                >
                  Resolve
                </button>
              )}
              <button
                type="button"
                onClick={() => onDismissReview(currentReview.id)}
              >
                Dismiss
              </button>
              <button type="button" onClick={onSkipReview}>
                Skip
              </button>
            </div>
          </article>
        ) : (
          <p>No open review items.</p>
        )}
      </div>
      {reconstruction.days.length === 0 ? (
        <p>No usable media has been grouped yet.</p>
      ) : (
        <div className="simple-list" role="list">
          {reconstruction.days.map((day) => (
            <article className="outline-day" key={day.id} role="listitem">
              <h3>{day.title ?? day.date}</h3>
              {day.stops.map((stop) => (
                <div className="outline-stop" key={stop.id}>
                  <div className="outline-stop-heading">
                    <span className="outline-stop-number">
                      {stop.displayPosition ?? String(stop.position)}
                    </span>
                    <strong>
                      {stop.title ?? `Stop ${stop.position}`}
                      {stop.placeName ? ` · ${stop.placeName}` : ""}
                    </strong>
                  </div>
                  <small>
                    {formatReconstructionTime(
                      stop.startsAt,
                      stop.startsAtLocal ?? null,
                      timezoneId,
                    )}{" "}
                    to{" "}
                    {formatReconstructionTime(
                      stop.endsAt,
                      stop.endsAtLocal ?? null,
                      timezoneId,
                    )}{" "}
                    · {stop.mediaCount} media · {stop.contributorCount}{" "}
                    contributors
                  </small>
                  <div className="moment-row">
                    {stop.moments.map((moment) => (
                      <span key={moment.id}>
                        {moment.title ?? `Moment ${moment.position}`}:{" "}
                        {moment.mediaCount} media, {moment.contributorCount}{" "}
                        contributors
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </article>
          ))}
        </div>
      )}
      {reconstruction.reviewItems.length > 0 ? (
        <div className="review-list">
          <h3>Review</h3>
          {reconstruction.reviewItems.map((item) => (
            <p key={item.id}>
              <strong>{item.itemType}</strong>: {item.message}
            </p>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function SimilarityGroupsPanel({
  groups,
  onChangeRepresentative,
}: {
  groups: SimilarityGroupResponse[];
  onChangeRepresentative: (groupId: string, mediaId: string) => void;
}) {
  if (groups.length === 0) {
    return null;
  }
  return (
    <section className="similarity-panel" aria-labelledby="similarity-title">
      <div>
        <h3 id="similarity-title">Similar photo stacks</h3>
        <p>Duplicate and near-duplicate versions stay preserved.</p>
      </div>
      <div className="simple-list">
        {groups.map((group) => (
          <details className="similarity-group" key={group.id}>
            <summary>
              <strong>{group.memberCount} versions</strong>
              <small>
                {group.groupType.replace("_", " ")} · confidence{" "}
                {group.confidence ?? "unknown"}
              </small>
            </summary>
            <p>{group.reason}</p>
            <div className="simple-list">
              {group.members.map((member) => (
                <div className="simple-row" key={member.mediaItemId}>
                  <div>
                    <strong>
                      {member.filename ?? "Untitled image"}
                      {member.isRepresentative ? " · representative" : ""}
                    </strong>
                    <small>
                      {member.contributor} · technical{" "}
                      {member.technicalScore ?? "unknown"} · similarity{" "}
                      {member.similarityScore ?? "unknown"}
                    </small>
                  </div>
                  {!member.isRepresentative ? (
                    <button
                      type="button"
                      onClick={() =>
                        onChangeRepresentative(group.id, member.mediaItemId)
                      }
                    >
                      Use as representative
                    </button>
                  ) : null}
                </div>
              ))}
            </div>
          </details>
        ))}
      </div>
    </section>
  );
}

function MediaList({
  media,
  onRetry,
  onVisibilityChange,
  canChangeVisibility,
  onDelete,
  timezoneId,
}: {
  media: MediaItemResponse[];
  onRetry?: (item: MediaItemResponse) => void;
  onVisibilityChange?: (item: MediaItemResponse, visibility: string) => void;
  canChangeVisibility?: (item: MediaItemResponse) => boolean;
  onDelete?: (item: MediaItemResponse) => void;
  timezoneId?: string;
}) {
  const [selectedPhotoId, setSelectedPhotoId] = useState<string | null>(null);
  const galleryPhotos = useMemo(
    () => media.map(galleryPhotoFromMediaItem),
    [media],
  );
  if (media.length === 0) {
    return <p>No processed media yet.</p>;
  }
  const visibilityLabels: Record<string, string> = {
    trip: "Member only",
    story: "Public",
    private: "Private",
    excluded: "Excluded",
  };
  return (
    <>
      <div className="media-list" role="list">
        {media.map((item) => (
          <article className="media-row" key={item.id} role="listitem">
            <button
              className="thumb-frame"
              type="button"
              onClick={() => setSelectedPhotoId(item.id)}
              aria-label={`Open ${item.filename ?? "photo"}`}
            >
              {item.thumbnail?.downloadUrl ? (
                <img src={item.thumbnail.downloadUrl} alt="" />
              ) : (
                <span>{item.processingState}</span>
              )}
            </button>
            <div className="media-details">
              <strong>{item.filename ?? "Untitled image"}</strong>
              <small>
                {item.processingState} · {item.contributor}
                {(item.similarityGroupCount ?? 1) > 1
                  ? ` · stack of ${item.similarityGroupCount ?? 1}${
                      item.isSimilarityRepresentative ? " · representative" : ""
                    }`
                  : ""}
              </small>
              <small className="media-state">
                {visibilityLabels[item.visibility] ?? item.visibility}
              </small>
              <dl>
                <div>
                  <dt>Captured</dt>
                  <dd>{formatDate(item.capturedAt ?? null, timezoneId)}</dd>
                </div>
                <div>
                  <dt>GPS</dt>
                  <dd>{item.gpsPresent ? "Present" : "Not found"}</dd>
                </div>
                <div>
                  <dt>Dimensions</dt>
                  <dd>
                    {item.width && item.height
                      ? `${item.width} × ${item.height}`
                      : "Unknown"}
                  </dd>
                </div>
              </dl>
              {item.errorMessage ? (
                <p className="error">{item.errorMessage}</p>
              ) : null}
              {item.processingState === "failed" && onRetry ? (
                <button type="button" onClick={() => onRetry(item)}>
                  Retry processing
                </button>
              ) : null}
              {onVisibilityChange &&
              (canChangeVisibility ? canChangeVisibility(item) : true) ? (
                <div className="media-actions">
                  <div
                    className="visibility-toggle"
                    role="group"
                    aria-label="Photo visibility"
                  >
                    <button
                      type="button"
                      className={item.visibility === "trip" ? "active" : ""}
                      aria-pressed={item.visibility === "trip"}
                      onClick={() => onVisibilityChange(item, "trip")}
                    >
                      Member only
                    </button>
                    <button
                      type="button"
                      className={
                        item.visibility === "story" && item.includeInStory
                          ? "active"
                          : ""
                      }
                      aria-pressed={
                        item.visibility === "story" && item.includeInStory
                      }
                      onClick={() => onVisibilityChange(item, "story")}
                    >
                      Public
                    </button>
                  </div>
                  {onDelete ? (
                    <button type="button" onClick={() => onDelete(item)}>
                      Delete
                    </button>
                  ) : null}
                </div>
              ) : null}
            </div>
          </article>
        ))}
      </div>
      <PhotoBrowser
        photos={galleryPhotos}
        selectedPhotoId={selectedPhotoId}
        timezoneId={timezoneId}
        onClose={() => setSelectedPhotoId(null)}
        onSelect={setSelectedPhotoId}
      />
    </>
  );
}

type StoryDayLabelSource = {
  date?: string | null;
  position?: number;
  title?: string | null;
};

function storyDayLabel(day: StoryDayLabelSource | null | undefined): string {
  if (!day) {
    return "Day";
  }
  return day.title?.trim() || storyDayDateLabel(day);
}

function storyDayDateLabel(
  day: StoryDayLabelSource | null | undefined,
): string {
  if (!day) {
    return "Day";
  }
  const dateLabel = formatShortCalendarDate(day.date ?? null);
  return dateLabel || `Day ${day.position ?? ""}`.trim();
}

function timelineDayDateParts(day: StoryDayLabelSource): {
  weekday: string;
  day: string;
} {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day.date ?? "");
  if (!match) {
    return {
      weekday: `Day ${day.position ?? ""}`.trim(),
      day: "",
    };
  }
  const [, year, month, dayOfMonth] = match;
  const date = new Date(Number(year), Number(month) - 1, Number(dayOfMonth));
  return {
    weekday: new Intl.DateTimeFormat(undefined, { weekday: "short" })
      .format(date)
      .toUpperCase(),
    day: String(Number(dayOfMonth)),
  };
}

function formatShortCalendarDate(value: string | null): string {
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

function formatDate(value: string | null, timezoneId?: string): string {
  if (!value) {
    return "Unknown";
  }
  const options: Intl.DateTimeFormatOptions = {
    dateStyle: "medium",
    timeStyle: "short",
  };
  if (timezoneId) {
    options.timeZone = timezoneId;
  }
  try {
    return new Intl.DateTimeFormat(undefined, options).format(new Date(value));
  } catch (error) {
    if (error instanceof RangeError && timezoneId) {
      return new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: "UTC",
      }).format(new Date(value));
    }
    throw error;
  }
}

function formatReconstructionTime(
  utcValue: string | null,
  localValue: string | null,
  timezoneId?: string,
): string {
  if (localValue) {
    return formatFloatingDate(localValue);
  }
  return formatDate(utcValue, timezoneId);
}

function formatTimelineStopTime(
  utcValue: string | null,
  localValue: string | null,
  timezoneId?: string,
): string {
  if (localValue) {
    return formatFloatingTime(localValue);
  }
  if (!utcValue) {
    return "Unknown";
  }
  try {
    return new Intl.DateTimeFormat(undefined, {
      hour: "numeric",
      minute: "2-digit",
      timeZone: timezoneId,
    }).format(new Date(utcValue));
  } catch {
    return new Intl.DateTimeFormat(undefined, {
      hour: "numeric",
      minute: "2-digit",
      timeZone: "UTC",
    }).format(new Date(utcValue));
  }
}

function formatFloatingDate(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value);
  if (!match) {
    return value;
  }
  const [, year, month, day, hour, minute] = match;
  const date = new Date(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour),
    Number(minute),
  );
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatFloatingTime(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value);
  if (!match) {
    return value;
  }
  const [, year, month, day, hour, minute] = match;
  const date = new Date(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour),
    Number(minute),
  );
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}
