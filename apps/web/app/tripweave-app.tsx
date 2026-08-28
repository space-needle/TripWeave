"use client";

import {
  type CSSProperties,
  ChangeEvent,
  DragEvent,
  FormEvent,
  Fragment,
  KeyboardEvent,
  TouchEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { flushSync } from "react-dom";
import NextImage from "next/image";
import maplibregl, {
  GeoJSONSource,
  LngLatBounds,
  Map as MapLibreMap,
  Marker,
} from "maplibre-gl";
import QRCode from "qrcode";
import {
  AdminDashboardResponse,
  ApiError,
  api,
  guestApi,
  uploadWithProgress,
} from "./api-client";
import type {
  AreaVisitResponse,
  AreaVisitStopResponse,
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
  TripQuotaResponse,
  TripMapPointResponse,
  TripResponse,
  TripsMapPointsResponse,
  UploadFileResponse,
  UploadQuotaResponse,
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
import { groupTripsByYear } from "./trip-list";

type GalleryPhoto = {
  id: string;
  imageUrl: string | null;
  thumbnailUrl: string | null;
  filename: string | null;
  contributor: string;
  capturedAt: string | null;
  capturedAtLocal?: string | null;
  contextLabel?: string | null;
};

type AuthMode = "login" | "register";
type LoadState = "loading" | "ready";
type OnboardingView = "hidden" | "welcome" | "example";
type MobileWorkspaceTab =
  | "story"
  | "timeline"
  | "photos"
  | "share"
  | "tripSettings"
  | "appSettings"
  | "trips"
  | "tripBrowse";
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
  | "trips"
  | "browse"
  | "settings"
  | "help";
type TimelineMetricIconName = "stops" | "camera" | "travelers";

type TripForm = {
  title: string;
  description: string;
  startDate: string;
  endDate: string;
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

const emptyTripForm: TripForm = {
  title: "",
  description: "",
  startDate: "",
  endDate: "",
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
    dayCutoffHour: Number(form.dayCutoffHour),
  };
}

function toCreatePayload(form: TripForm) {
  return {
    title: form.title,
    description: form.description || null,
    startDate: form.startDate || null,
    endDate: form.endDate || null,
  };
}

function fromTrip(trip: TripResponse): TripForm {
  return {
    title: trip.title,
    description: trip.description ?? "",
    startDate: trip.startDate ?? "",
    endDate: trip.endDate ?? "",
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
  if (path === "/admin" || path === "/admin/") {
    return <AdminWorkspace />;
  }
  if (path.startsWith("/story/")) {
    const storyPath = path.slice("/story/".length);
    const slideshowSuffix = "/slideshow";
    const isSlideshow = storyPath.endsWith(slideshowSuffix);
    const publicPath = isSlideshow
      ? storyPath.slice(0, -slideshowSuffix.length)
      : storyPath;
    const [slug, versionMarker, versionText] = publicPath.split("/");
    const versionNumber =
      versionMarker === "v" && /^\d+$/.test(versionText ?? "")
        ? Number(versionText)
        : undefined;
    return (
      <PublicStoryViewer
        slug={decodeURIComponent(slug)}
        versionNumber={versionNumber}
        initialView={isSlideshow ? "slideshow" : "story"}
      />
    );
  }
  return <OwnerWorkspace />;
}

function AdminWorkspace() {
  return (
    <main className="app-shell admin-shell">
      <AdminDashboard />
    </main>
  );
}

function OwnerWorkspace() {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [user, setUser] = useState<UserResponse | null>(null);
  const [trips, setTrips] = useState<TripResponse[]>([]);
  const [tripQuota, setTripQuota] = useState<TripQuotaResponse | null>(null);
  const [selectedTripId, setSelectedTripId] = useState<string | null>(null);
  const selectedTripIdRef = useRef<string | null>(null);
  const deletedMediaIdsRef = useRef(new Set<string>());
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
  const [autoStoryRefreshUntil, setAutoStoryRefreshUntil] = useState(0);
  const [uploadSessions, setUploadSessions] = useState<UploadSessionResponse[]>(
    [],
  );
  const [uploadQuota, setUploadQuota] = useState<UploadQuotaResponse | null>(
    null,
  );
  const [uploadError, setUploadError] = useState("");
  const [media, setMedia] = useState<MediaItemResponse[]>([]);
  const [similarityGroups, setSimilarityGroups] = useState<
    SimilarityGroupResponse[]
  >([]);
  const [mediaError, setMediaError] = useState("");
  const [locationMedia, setLocationMedia] = useState<MediaItemResponse | null>(
    null,
  );
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
  const [mobileTab, setMobileTab] = useState<MobileWorkspaceTab>("story");
  const [onboardingView, setOnboardingView] =
    useState<OnboardingView>("hidden");
  const [mobileOverflowMenuOpen, setMobileOverflowMenuOpen] = useState(false);
  const [ownerStoryPhotosOpen, setOwnerStoryPhotosOpen] = useState(false);
  const [ownerSlideshowOpen, setOwnerSlideshowOpen] = useState(false);
  const [tripMapPoints, setTripMapPoints] =
    useState<TripsMapPointsResponse | null>(null);
  const [tripMapStartDate, setTripMapStartDate] = useState("");
  const [tripMapEndDate, setTripMapEndDate] = useState("");
  const [tripMapError, setTripMapError] = useState("");
  const [isTripMapLoading, setIsTripMapLoading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<
    Record<string, UploadProgress>
  >({});
  const localFiles = useRef<Map<string, File>>(new Map());
  const abortUpload = useRef<Map<string, () => void>>(new Map());

  const selectedTrip = useMemo(
    () => trips.find((trip) => trip.id === selectedTripId) ?? trips[0] ?? null,
    [selectedTripId, trips],
  );
  const tripYearGroups = useMemo(() => groupTripsByYear(trips), [trips]);
  const canOrganizeSelectedTrip =
    selectedTrip !== null && ["owner", "editor"].includes(selectedTrip.role);
  const tripQuotaReached =
    tripQuota !== null &&
    tripQuota.maxTripsPerUser !== null &&
    tripQuota.ownedTripCount >= tripQuota.maxTripsPerUser;
  const uploadQuotaReached =
    uploadQuota !== null &&
    (uploadQuota.remainingFileCount === 0 ||
      uploadQuota.monthlyUploadedBytes >= uploadQuota.monthlyUploadBytes);
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

  const loadTripMapPoints = useCallback(async (start = "", end = "") => {
    setIsTripMapLoading(true);
    setTripMapError("");
    try {
      setTripMapPoints(
        await api.tripMapPoints(start || undefined, end || undefined),
      );
    } catch (error) {
      setTripMapError(messageFrom(error));
    } finally {
      setIsTripMapLoading(false);
    }
  }, []);

  const loadTrips = useCallback(
    async (preferredTripId: string | null = null) => {
      const result = await api.trips();
      setTrips(result.trips);
      setTripQuota(result.quota);
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
      setUploadQuota(null);
      return;
    }
    const result = await api.uploadSessions(tripId);
    setUploadSessions(result.uploadSessions);
    setUploadQuota(result.quota);
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
    setMedia(
      result.media.filter((item) => !deletedMediaIdsRef.current.has(item.id)),
    );
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

  function closeMobileMenus() {
    setMobileOverflowMenuOpen(false);
  }

  function selectTrip(trip: TripResponse) {
    deletedMediaIdsRef.current.clear();
    setOwnerSlideshowOpen(false);
    closeMobileMenus();
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

  function selectTripById(tripId: string) {
    const trip = trips.find((item) => item.id === tripId);
    if (trip) {
      selectTrip(trip);
    }
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
    if (!user || mobileTab !== "tripBrowse") {
      return;
    }
    const timeout = setTimeout(() => {
      void loadTripMapPoints(tripMapStartDate, tripMapEndDate);
    }, 0);
    return () => clearTimeout(timeout);
  }, [loadTripMapPoints, mobileTab, tripMapEndDate, tripMapStartDate, user]);

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
        setMedia(
          result.media.filter(
            (item) => !deletedMediaIdsRef.current.has(item.id),
          ),
        );
        setMediaError("");
        const keepPolling = result.media.some((item) =>
          ["pending", "processing"].includes(item.processingState),
        );
        if (keepPolling) {
          timeout = setTimeout(poll, delay);
          delay = Math.min(delay * 1.6, 10000);
        } else if (hasProcessingMedia) {
          setAutoStoryRefreshUntil(Date.now() + 120_000);
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
    const awaitingAutoStoryUpdate = Date.now() < autoStoryRefreshUntil;
    if (
      !selectedTrip?.id ||
      (!storyUpdateNeeded && !awaitingAutoStoryUpdate) ||
      isReconstructingStory
    ) {
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
    autoStoryRefreshUntil,
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
      setOnboardingView("hidden");
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
      setTripQuota(null);
      setSelectedTripSelection(null);
      setUploadSessions([]);
      setUploadQuota(null);
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
      setOnboardingView("hidden");
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
      const trip = await api.createTrip(toCreatePayload(createForm));
      await loadTrips(trip.id);
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
      await loadTrips();
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
    if (
      uploadQuota !== null &&
      uploadQuota.remainingFileCount !== null &&
      files.length > uploadQuota.remainingFileCount
    ) {
      setUploadError(
        `This trip can hold ${uploadQuota.maxFilesPerTrip} photos. Remove or cancel an upload before adding more.`,
      );
      return;
    }
    try {
      const session = await api.createUploadSession(selectedTrip.id, {
        files: files.map((file) => ({
          filename: file.name,
          byteSize: file.size,
          mimeType: uploadMimeType(file),
        })),
      });
      setUploadSessions((current) => [session, ...current]);
      setUploadQuota(session.quota);
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

  async function deleteOwnMedia(item: MediaItemResponse) {
    if (
      !selectedTrip ||
      !window.confirm(`Delete ${item.filename ?? "this photo"}?`)
    ) {
      return;
    }
    setMediaError("");
    try {
      await api.updateMedia(item.id, { deleted: true });
      deletedMediaIdsRef.current.add(item.id);
      setMedia((current) =>
        current.filter((mediaItem) => mediaItem.id !== item.id),
      );
      await Promise.all([
        loadMedia(selectedTrip.id),
        loadReconstruction(selectedTrip.id),
        loadStoryProjection(selectedTrip.id),
      ]);
    } catch (error) {
      setMediaError(messageFrom(error));
    }
  }

  async function saveMediaLocation(latitude: number, longitude: number) {
    if (!selectedTrip || !locationMedia) return;
    setMediaError("");
    try {
      await api.createEditOperation(selectedTrip.id, {
        operationType: "move_media_on_map",
        payload: { mediaItemId: locationMedia.id, latitude, longitude },
      });
      setLocationMedia(null);
      await Promise.all([
        loadMedia(selectedTrip.id),
        loadReconstruction(selectedTrip.id),
        loadStoryProjection(selectedTrip.id),
      ]);
    } catch (error) {
      setMediaError(messageFrom(error));
      throw error;
    }
  }

  async function createInvite() {
    if (!selectedTrip) {
      return;
    }
    setCollaborationError("");
    try {
      await api.createInvitation(selectedTrip.id);
      await loadCollaboration(selectedTrip.id);
    } catch (error) {
      setCollaborationError(messageFrom(error));
    }
  }

  async function copyInviteUrl(url: string) {
    if (typeof navigator === "undefined") {
      return;
    }
    await navigator.clipboard.writeText(url);
  }

  async function copyLatestShareUrl() {
    if (!latestShareUrl || typeof navigator === "undefined") {
      return;
    }
    await navigator.clipboard.writeText(latestShareUrl);
  }

  async function copyPublicationUrl(url: string) {
    if (typeof navigator === "undefined") {
      return;
    }
    await navigator.clipboard.writeText(url);
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

  async function deleteStop(stopId: string) {
    if (!selectedTrip) {
      return;
    }
    setReconstructionError("");
    try {
      await api.createEditOperation(selectedTrip.id, {
        operationType: "delete_stop",
        payload: { stopId },
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
      setLatestShareUrl(result.shareLink.latestStoryUrl ?? "");
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

  const isOnboardingVisible = trips.length === 0 || onboardingView !== "hidden";

  if (isOnboardingVisible) {
    return (
      <main className="app-shell onboarding-shell">
        <header className="app-header onboarding-header">
          <strong>TripWeave</strong>
          <div className="onboarding-header-actions">
            {trips.length > 0 ? (
              <button
                className="secondary-button"
                type="button"
                onClick={() => setOnboardingView("hidden")}
              >
                Back to my trips
              </button>
            ) : null}
            <button type="button" onClick={logout} disabled={isBusy}>
              Logout
            </button>
          </div>
        </header>

        {onboardingView === "example" ? (
          <ExampleTripPreview onBack={() => setOnboardingView("welcome")} />
        ) : (
          <section className="onboarding" aria-labelledby="onboarding-title">
            <div className="onboarding-intro">
              <p className="eyebrow">Your shared travel story starts here</p>
              <h1 id="onboarding-title">
                Turn scattered travel photos into one shared story.
              </h1>
              <p className="onboarding-lede">
                Create a trip, invite the people who were there, and weave
                everyone&apos;s moments into a journey you can revisit.
              </p>

              <ol className="onboarding-steps" aria-label="How TripWeave works">
                <li>
                  <span>01</span>
                  <div>
                    <strong>Create a trip</strong>
                    <p>Give the journey a home before the photos arrive.</p>
                  </div>
                </li>
                <li>
                  <span>02</span>
                  <div>
                    <strong>Add photos together</strong>
                    <p>Invite fellow travelers to contribute their moments.</p>
                  </div>
                </li>
                <li>
                  <span>03</span>
                  <div>
                    <strong>Revisit the story</strong>
                    <p>See the trip take shape as a map and timeline.</p>
                  </div>
                </li>
              </ol>
              <button
                className="secondary-button onboarding-example-button"
                type="button"
                onClick={() => setOnboardingView("example")}
              >
                Explore an example trip
              </button>
            </div>

            <section
              className="onboarding-create panel"
              aria-labelledby="create-first-trip-title"
            >
              <div>
                <p className="eyebrow">Step 1</p>
                <h2 id="create-first-trip-title">Create your first trip</h2>
                <p>Give it a name and add any details you already know.</p>
              </div>
              <form className="stack" onSubmit={createTrip}>
                <TripFields
                  form={createForm}
                  onChange={setCreateForm}
                  showDayCutoffHour={false}
                />
                {tripQuota ? (
                  <p
                    className={
                      tripQuotaReached
                        ? "quota-message quota-reached"
                        : "quota-message"
                    }
                    role="status"
                  >
                    {tripQuotaMessage(tripQuota)}
                  </p>
                ) : null}
                {tripError ? (
                  <p className="error" role="alert">
                    {tripError}
                  </p>
                ) : null}
                <button type="submit" disabled={isBusy || tripQuotaReached}>
                  {isBusy ? "Creating trip..." : "Create your first trip"}
                </button>
              </form>
            </section>
          </section>
        )}
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
              closeMobileMenus();
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
            closeMobileMenus();
            setOwnerSlideshowOpen(true);
          }}
          title="Play slideshow"
        >
          <StoryHeaderIcon action="slideshow" />
        </button>
        <button
          type="button"
          aria-label="More options"
          aria-expanded={mobileOverflowMenuOpen}
          className={mobileOverflowMenuOpen ? "active" : ""}
          onClick={() => {
            setOwnerStoryPhotosOpen(false);
            setMobileOverflowMenuOpen((current) => !current);
          }}
          title="More options"
        >
          <StoryHeaderIcon action="more" />
        </button>
      </nav>
      {mobileOverflowMenuOpen ? (
        <nav className="mobile-overflow-menu" aria-label="More options">
          <div className="mobile-overflow-trip">
            <span className="mobile-overflow-trip-label">Current trip</span>
            <span className="mobile-overflow-trip-title">
              {selectedTrip?.title ?? "Current trip"}
            </span>
          </div>
          <div
            className="mobile-overflow-trip-actions"
            aria-label="Current trip actions"
          >
            <button
              type="button"
              aria-label="Add photos"
              aria-pressed={mobileTab === "photos"}
              className={mobileTab === "photos" ? "active" : ""}
              onClick={() => {
                setOwnerStoryPhotosOpen(false);
                closeMobileMenus();
                setMobileTab("photos");
              }}
              title="Add photos"
            >
              <StoryHeaderIcon action="upload" />
              <span className="mobile-menu-label">Add photos</span>
            </button>
            {canManageSelectedTrip ? (
              <>
                <button
                  type="button"
                  aria-label="Share trip"
                  aria-pressed={mobileTab === "share"}
                  className={mobileTab === "share" ? "active" : ""}
                  disabled={
                    !["owner", "editor"].includes(selectedTrip?.role ?? "")
                  }
                  onClick={() => {
                    setOwnerStoryPhotosOpen(false);
                    closeMobileMenus();
                    setMobileTab("share");
                  }}
                  title="Share trip"
                >
                  <StoryHeaderIcon action="share" />
                  <span className="mobile-menu-label">Share trip</span>
                </button>
                <button
                  type="button"
                  aria-label="Manage trip"
                  aria-pressed={mobileTab === "tripSettings"}
                  className={mobileTab === "tripSettings" ? "active" : ""}
                  disabled={
                    !["owner", "editor"].includes(selectedTrip?.role ?? "")
                  }
                  onClick={() => {
                    setOwnerStoryPhotosOpen(false);
                    closeMobileMenus();
                    setMobileTab("tripSettings");
                  }}
                  title="Manage trip"
                >
                  <StoryHeaderIcon action="manage" />
                  <span className="mobile-menu-label">Manage trip</span>
                </button>
              </>
            ) : null}
          </div>
          <div className="mobile-overflow-divider" aria-hidden="true" />
          <div
            className="mobile-overflow-global-actions"
            aria-label="App-wide actions"
          >
            <button
              type="button"
              aria-label="Trips"
              aria-pressed={mobileTab === "trips"}
              className={mobileTab === "trips" ? "active" : ""}
              onClick={() => {
                setOwnerStoryPhotosOpen(false);
                closeMobileMenus();
                setMobileTab("trips");
              }}
              title="Trips"
            >
              <StoryHeaderIcon action="trips" />
              <span className="mobile-menu-label">Trips</span>
            </button>
            <button
              type="button"
              aria-label="Trip Map"
              aria-pressed={mobileTab === "tripBrowse"}
              className={mobileTab === "tripBrowse" ? "active" : ""}
              onClick={() => {
                setOwnerStoryPhotosOpen(false);
                closeMobileMenus();
                setMobileTab("tripBrowse");
              }}
              title="Trip Map"
            >
              <StoryHeaderIcon action="browse" />
              <span className="mobile-menu-label">Trip Map</span>
            </button>
            <button
              type="button"
              aria-label="Settings"
              aria-pressed={mobileTab === "appSettings"}
              className={mobileTab === "appSettings" ? "active" : ""}
              onClick={() => {
                setOwnerStoryPhotosOpen(false);
                closeMobileMenus();
                setMobileTab("appSettings");
              }}
              title="Settings"
            >
              <StoryHeaderIcon action="settings" />
              <span className="mobile-menu-label">Settings</span>
            </button>
            <button
              type="button"
              aria-label="How TripWeave works"
              onClick={() => {
                setOwnerStoryPhotosOpen(false);
                closeMobileMenus();
                setOnboardingView("welcome");
              }}
              title="How TripWeave works"
            >
              <StoryHeaderIcon action="help" />
              <span className="mobile-menu-label">How TripWeave works</span>
            </button>
          </div>
        </nav>
      ) : null}

      <section className="workspace trip-workspace">
        <div
          className={`mobile-page-header ${
            mobileTab === "trips" ? "mobile-tab-active" : ""
          }`}
          data-mobile-tab-panel="trips"
        >
          <div>
            <h2>Trips</h2>
            <p>
              {trips.length} trip{trips.length === 1 ? "" : "s"}
            </p>
          </div>
        </div>
        <aside
          className={`trip-nav panel ${
            mobileTab === "trips" ? "mobile-tab-active" : ""
          }`}
          aria-label="Trip navigation"
          data-mobile-tab-panel="trips"
        >
          <nav className="trip-primary-nav" aria-label="Workspace sections">
            <a
              href="#trip-stage-title"
              className={mobileTab === "tripBrowse" ? "" : "active"}
            >
              Story
            </a>
            <button
              type="button"
              className={mobileTab === "tripBrowse" ? "active" : ""}
              onClick={() => {
                setOwnerStoryPhotosOpen(false);
                setMobileTab("tripBrowse");
              }}
            >
              Trip Map
            </button>
            <a href="#add-photos-panel">Photos</a>
            <a href="#settings-panel">Manage trip</a>
            {selectedTrip && ["owner", "editor"].includes(selectedTrip.role) ? (
              <>
                <a href="#review-panel">Review</a>
              </>
            ) : null}
          </nav>
          <section
            className="trip-list-section"
            aria-labelledby="trip-list-title"
          >
            <div className="nav-section-heading">
              <h2 id="trip-list-title">Trips</h2>
              <span>
                {trips.length} trip{trips.length === 1 ? "" : "s"}
              </span>
            </div>
            {trips.length === 0 ? (
              <p>No trips yet.</p>
            ) : (
              <div className="trip-list">
                {tripYearGroups.map((group) => (
                  <section
                    className="trip-year-group"
                    key={group.year}
                    aria-labelledby={`trip-year-${group.year}`}
                  >
                    <h3 id={`trip-year-${group.year}`}>{group.year}</h3>
                    <div className="trip-year-cards">
                      {group.trips.map((trip) => (
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
                  </section>
                ))}
              </div>
            )}
          </section>
          <details className="management-panel">
            <summary>Create trip</summary>
            <form className="stack" onSubmit={createTrip}>
              <TripFields
                form={createForm}
                onChange={setCreateForm}
                showDayCutoffHour={false}
              />
              {tripQuota ? (
                <p
                  className={
                    tripQuotaReached
                      ? "quota-message quota-reached"
                      : "quota-message"
                  }
                  role="status"
                >
                  {tripQuotaMessage(tripQuota)}
                </p>
              ) : null}
              <button type="submit" disabled={isBusy || tripQuotaReached}>
                Create trip
              </button>
            </form>
          </details>
          <button
            className="tripweave-guide-link"
            type="button"
            onClick={() => setOnboardingView("welcome")}
          >
            <span>How TripWeave works</span>
            <small>View onboarding</small>
          </button>
        </aside>

        <section
          className={`trip-stage ${
            ["story", "timeline", "tripBrowse"].includes(mobileTab)
              ? "mobile-tab-active"
              : ""
          }`}
          aria-labelledby="trip-stage-title"
          data-mobile-tab-panel="story"
        >
          {mobileTab === "tripBrowse" ? (
            <TripBrowserPanel
              data={tripMapPoints}
              endDate={tripMapEndDate}
              error={tripMapError}
              isLoading={isTripMapLoading}
              selectedTripId={selectedTrip?.id ?? null}
              startDate={tripMapStartDate}
              trips={trips}
              onClearFilters={() => {
                setTripMapStartDate("");
                setTripMapEndDate("");
              }}
              onEndDateChange={setTripMapEndDate}
              onSelectTrip={selectTripById}
              onStartDateChange={setTripMapStartDate}
            />
          ) : selectedTrip ? (
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
                  onDeleteStop={
                    canOrganizeSelectedTrip ? deleteStop : undefined
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
          <div
            className={`mobile-page-header mobile-trip-context-header ${
              mobileTab === "photos" ? "mobile-tab-active" : ""
            }`}
            data-mobile-tab-panel="photos"
          >
            <div>
              {selectedTrip ? (
                <>
                  <h2>{selectedTrip.title}</h2>
                  <p>
                    {selectedTrip.startDate} - {selectedTrip.endDate}
                  </p>
                </>
              ) : (
                <p>Select a trip before adding photos.</p>
              )}
              <h2>Add photos</h2>
            </div>
          </div>
          <div
            className={`mobile-page-header mobile-trip-context-header ${
              mobileTab === "tripSettings" ? "mobile-tab-active" : ""
            }`}
            data-mobile-tab-panel="tripSettings"
          >
            <div>
              {selectedTrip ? (
                <>
                  <h2>{selectedTrip.title}</h2>
                  <p>
                    {selectedTrip.startDate} - {selectedTrip.endDate}
                  </p>
                </>
              ) : (
                <p>Select a trip to manage its details.</p>
              )}
              <h2>Manage trip</h2>
            </div>
            {canOrganizeSelectedTrip ? (
              <div className="mobile-manage-trip-update">
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
                    <span className="button-spinner" aria-hidden="true" />
                  ) : null}
                  {storyActionButtonLabel}
                </button>
                <p className="mobile-manage-trip-update-description">
                  Refreshes your map and timeline using the latest photos.
                </p>
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
          </div>
          <div
            className={`mobile-page-header mobile-trip-context-header ${
              mobileTab === "share" ? "mobile-tab-active" : ""
            }`}
            data-mobile-tab-panel="share"
          >
            <div>
              {selectedTrip ? (
                <>
                  <h2>{selectedTrip.title}</h2>
                  <p>
                    {selectedTrip.startDate} - {selectedTrip.endDate}
                  </p>
                </>
              ) : (
                <p>Select a trip before sharing it.</p>
              )}
              <h2>Share trip</h2>
            </div>
          </div>
          <section
            className={`management-panel ${
              mobileTab === "photos" ? "mobile-tab-active" : ""
            }`}
            id="add-photos-panel"
            data-mobile-tab-panel="photos"
          >
            <div className="management-panel-static-heading">
              <span className="management-summary-copy">
                <strong>Add photos</strong>
                <span>Upload JPEG or HEIC photos to this trip</span>
              </span>
            </div>
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
                      disabled={uploadQuotaReached}
                      multiple
                      type="file"
                      onChange={onFileInput}
                    />
                  </label>
                  <p>
                    {uploadQuota
                      ? uploadQuotaMessage(uploadQuota)
                      : "JPEG and HEIC"}
                  </p>
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
              </div>
            ) : (
              <p>Select a trip before uploading photos.</p>
            )}
          </section>
          <details
            className={`management-panel ${
              mobileTab === "photos" ? "mobile-tab-active" : ""
            }`}
            id="photos-panel"
            data-mobile-tab-panel="photos"
          >
            <summary>
              <span className="management-summary-copy">
                <strong>Photo library</strong>
                <span>Browse and manage trip photos</span>
              </span>
              {selectedTrip ? (
                <small>
                  {media.length} photo{media.length === 1 ? "" : "s"}
                </small>
              ) : null}
            </summary>
            {selectedTrip ? (
              <div className="stack">
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
                  onDelete={deleteOwnMedia}
                  onAdjustLocation={setLocationMedia}
                  timezoneId={selectedTrip?.timezoneId}
                />
                {locationMedia ? (
                  <MediaLocationDialog
                    media={locationMedia}
                    onCancel={() => setLocationMedia(null)}
                    onSave={saveMediaLocation}
                  />
                ) : null}
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
              <p>Select a trip before viewing its photo library.</p>
            )}
          </details>

          {selectedTrip?.role === "owner" ? (
            <>
              <details
                className={`management-panel ${
                  mobileTab === "share" ? "mobile-tab-active" : ""
                }`}
                id="travelers-panel"
                data-mobile-tab-panel="share"
              >
                <summary>
                  <span className="management-summary-copy">
                    <strong>Invite travelers</strong>
                    <span>Invite friends to add photos</span>
                  </span>
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
                      Create shared invite link
                    </button>
                  </div>
                  <InvitationList
                    invitations={invitations}
                    onRevoke={revokeInvite}
                    onCopyUrl={(url) => void copyInviteUrl(url)}
                  />
                  <MemberRoster members={members} onRemove={removeMember} />
                </div>
              </details>
            </>
          ) : null}

          {selectedTrip && ["owner", "editor"].includes(selectedTrip.role) ? (
            <details
              className={`management-panel ${
                mobileTab === "share" ? "mobile-tab-active" : ""
              }`}
              id="publish-panel"
              data-mobile-tab-panel="share"
            >
              <summary>
                <span className="management-summary-copy">
                  <strong>Publish story</strong>
                  <span>Share a read-only story with anyone</span>
                </span>
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
                    <small>Latest published story</small>
                    <code>{latestShareUrl}</code>
                    <button type="button" onClick={copyLatestShareUrl}>
                      Copy link
                    </button>
                  </div>
                ) : null}
                <PublicationList
                  publications={publications}
                  onRevoke={revokeShareLink}
                  onCopyUrl={(url) => void copyPublicationUrl(url)}
                />
              </div>
            </details>
          ) : null}

          <details
            className={`management-panel ${
              mobileTab === "tripSettings" ? "mobile-tab-active" : ""
            }`}
            id="settings-panel"
            data-mobile-tab-panel="tripSettings"
          >
            <summary>
              <span className="management-summary-copy">
                <strong>Manage trip</strong>
                <span>Edit trip info or update its story</span>
              </span>
            </summary>
            <form className="stack" onSubmit={updateTrip}>
              {selectedTrip ? (
                <>
                  {canOrganizeSelectedTrip ? (
                    <div className="stack manage-trip-manual-update">
                      <div>
                        <strong>Update story</strong>
                        <p>
                          Rebuild the map and timeline from your latest photos.
                        </p>
                      </div>
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
                    </div>
                  ) : null}
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

          {selectedTrip && ["owner", "editor"].includes(selectedTrip.role) ? (
            <details
              className={`management-panel ${
                mobileTab === "tripSettings" ? "mobile-tab-active" : ""
              }`}
              id="review-panel"
              data-mobile-tab-panel="tripSettings"
              onToggle={(event) => {
                if (event.currentTarget.open) {
                  loadReviewDetails();
                }
              }}
            >
              <summary>
                <span className="management-summary-copy">
                  <strong>Review</strong>
                  <span>Resolve questions in your trip</span>
                </span>
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
        </aside>
        <div
          className={`mobile-page-header ${
            mobileTab === "appSettings" ? "mobile-tab-active" : ""
          }`}
          data-mobile-tab-panel="appSettings"
        >
          <div>
            <h2 id="app-settings-title">Settings</h2>
            <p>Account and workspace preferences</p>
          </div>
        </div>
        <section
          className={`panel mobile-app-settings ${
            mobileTab === "appSettings" ? "mobile-tab-active" : ""
          }`}
          aria-labelledby="app-settings-title"
          data-mobile-tab-panel="appSettings"
        >
          <div className="mobile-account-card">
            <div>
              <span>Signed in</span>
              <strong>{user.display_name}</strong>
            </div>
            <button type="button" onClick={logout} disabled={isBusy}>
              Logout
            </button>
          </div>
        </section>
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
  const [uploadQuota, setUploadQuota] = useState<UploadQuotaResponse | null>(
    null,
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
  const uploadQuotaReached =
    uploadQuota !== null &&
    (uploadQuota.remainingFileCount === 0 ||
      uploadQuota.monthlyUploadedBytes >= uploadQuota.monthlyUploadBytes);

  const loadContribution = useCallback(async () => {
    const [sessionResult, mediaResult] = await Promise.all([
      guestApi.uploadSessions(tripId),
      guestApi.media(tripId),
    ]);
    setUploadSessions(sessionResult.uploadSessions);
    setUploadQuota(sessionResult.quota);
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
    if (
      uploadQuota !== null &&
      uploadQuota.remainingFileCount !== null &&
      files.length > uploadQuota.remainingFileCount
    ) {
      setError(
        `This trip can hold ${uploadQuota.maxFilesPerTrip} photos. Remove or cancel an upload before adding more.`,
      );
      return;
    }
    try {
      const session = await guestApi.createUploadSession(tripId, {
        files: files.map((file) => ({
          filename: file.name,
          byteSize: file.size,
          mimeType: uploadMimeType(file),
        })),
      });
      setUploadSessions((current) => [session, ...current]);
      setUploadQuota(session.quota);
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
                  disabled={uploadQuotaReached}
                  multiple
                  type="file"
                  onChange={(event) =>
                    void uploadFiles(Array.from(event.target.files ?? []))
                  }
                />
              </label>
              <p
                className={
                  uploadQuotaReached
                    ? "quota-message quota-reached"
                    : "quota-message"
                }
                role="status"
              >
                {uploadQuota
                  ? uploadQuotaMessage(uploadQuota)
                  : "Only your uploads are shown here."}
              </p>
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

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes;
  let unitIndex = -1;
  do {
    value /= 1024;
    unitIndex += 1;
  } while (value >= 1024 && unitIndex < units.length - 1);
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}

function tripQuotaMessage(quota: TripQuotaResponse): string {
  if (quota.maxTripsPerUser === null) {
    return `Trip quota: ${quota.ownedTripCount} trips used · unlimited trips.`;
  }
  const remaining = Math.max(quota.maxTripsPerUser - quota.ownedTripCount, 0);
  if (remaining === 0) {
    return `Trip quota reached: ${quota.ownedTripCount} of ${quota.maxTripsPerUser} trips used. Ask an operator to move this account to a higher tier.`;
  }
  return `Trip quota: ${quota.ownedTripCount} of ${quota.maxTripsPerUser} used · ${remaining} remaining.`;
}

function uploadQuotaMessage(quota: UploadQuotaResponse): string {
  if (quota.monthlyUploadedBytes >= quota.monthlyUploadBytes) {
    return `Monthly upload quota reached: ${formatBytes(quota.monthlyUploadedBytes)} of ${formatBytes(quota.monthlyUploadBytes)} used. Ask an operator to move this account to a higher tier.`;
  }
  if (quota.remainingFileCount === 0) {
    return `Photo quota reached: ${quota.reservedFileCount} of ${quota.maxFilesPerTrip} slots used or reserved. Cancel an upload or ask an operator to move this trip to a higher tier.`;
  }
  if (quota.maxFilesPerTrip === null) {
    return `Photo quota: ${quota.reservedFileCount} slots used or reserved · unlimited photos.`;
  }
  return `Photo quota: ${quota.reservedFileCount} of ${quota.maxFilesPerTrip} slots used or reserved · ${quota.remainingFileCount} remaining.`;
}

function AdminDashboard() {
  const [dashboard, setDashboard] = useState<AdminDashboardResponse | null>(
    null,
  );
  const [adminLoadState, setAdminLoadState] = useState<
    "loading" | "ready" | "unavailable"
  >("loading");
  const [tiers, setTiers] = useState<import("./api-types").TierResponse[]>([]);
  const [userQuery, setUserQuery] = useState("");
  const [adminUsers, setAdminUsers] = useState<
    import("./api-types").AdminUserResponse[]
  >([]);
  const [pendingTierIds, setPendingTierIds] = useState<Record<string, string>>(
    {},
  );
  const [updatingUserId, setUpdatingUserId] = useState<string | null>(null);
  const [tierForm, setTierForm] = useState({
    slug: "",
    name: "",
    trips: "",
    photos: "",
    bytes: "",
  });
  const [adminError, setAdminError] = useState("");
  useEffect(() => {
    void api
      .adminDashboard()
      .then((result) => {
        setDashboard(result);
        setAdminLoadState("ready");
      })
      .catch(() => setAdminLoadState("unavailable"));
    void api
      .adminTiers()
      .then((result) => setTiers(result.tiers))
      .catch(() => undefined);
  }, []);
  if (adminLoadState === "loading") {
    return (
      <section className="panel stack" aria-label="Operations dashboard">
        <h1>Loading operations dashboard</h1>
      </section>
    );
  }
  if (!dashboard) {
    return (
      <section className="panel stack" aria-label="Operations dashboard">
        <h1>Operator access required</h1>
        <p>Sign in with an account configured for operator access.</p>
      </section>
    );
  }
  const latest = dashboard.trend.at(-1);
  return (
    <section className="admin-dashboard" aria-label="Operations dashboard">
      <div className="admin-heading">
        <h2>Operations overview</h2>
        <p>Usage, audience activity, and quota controls</p>
        <span>Last 30 days</span>
      </div>
      <section className="admin-section">
        <h3>Usage summary</h3>
        <div className="admin-metrics">
          <strong className="admin-metric">
            {dashboard.totals.users}
            <small>Users</small>
          </strong>
          <strong className="admin-metric">
            {dashboard.totals.trips}
            <small>Trips</small>
          </strong>
          <strong className="admin-metric">
            {dashboard.totals.photos}
            <small>Photos</small>
          </strong>
          <strong className="admin-metric">
            {latest?.active_users ?? 0}
            <small>Signed-in today</small>
          </strong>
          <strong className="admin-metric">
            {latest?.trip_views ?? 0}
            <small>Story views today</small>
          </strong>
        </div>
        <p className="admin-note">
          Signed-in users counts users who started a session that day. Story
          views count public story page requests; anonymous viewers are not
          mapped to TripWeave accounts.
        </p>
      </section>
      <section className="admin-section">
        <div className="admin-section-heading">
          <div>
            <h3>Daily activity</h3>
            <p>New accounts, content creation, and public story reach.</p>
          </div>
          <span>30 days</span>
        </div>
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>New users</th>
                <th>Signed-in users</th>
                <th>New trips</th>
                <th>Photos</th>
                <th>Story views</th>
                <th>Trips viewed</th>
              </tr>
            </thead>
            <tbody>
              {dashboard.trend.map((row) => (
                <tr key={row.day}>
                  <td>{row.day}</td>
                  <td>{row.users}</td>
                  <td>{row.active_users}</td>
                  <td>{row.trips}</td>
                  <td>{row.photos}</td>
                  <td>{row.trip_views}</td>
                  <td>{row.viewed_trips}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="admin-section">
        <div className="admin-section-heading">
          <div>
            <h3>Usage distributions</h3>
            <p>How usage is spread across users and trips.</p>
          </div>
        </div>
        <div className="admin-distribution-grid">
          <div className="admin-distribution-card">
            <strong>User trips</strong>
            <span>Average {dashboard.distributions.trips_avg ?? 0}</span>
            <small>
              p50 {dashboard.distributions.trips_p50 ?? 0} / p90{" "}
              {dashboard.distributions.trips_p90 ?? 0}
            </small>
          </div>
          <div className="admin-distribution-card">
            <strong>User photos</strong>
            <span>Average {dashboard.distributions.photos_avg ?? 0}</span>
            <small>
              p50 {dashboard.distributions.photos_p50 ?? 0} / p90{" "}
              {dashboard.distributions.photos_p90 ?? 0}
            </small>
          </div>
          <div className="admin-distribution-card">
            <strong>Photos per trip</strong>
            <span>Average {dashboard.distributions.trip_photos_avg ?? 0}</span>
            <small>
              p50 {dashboard.distributions.trip_photos_p50 ?? 0} / p90{" "}
              {dashboard.distributions.trip_photos_p90 ?? 0}
            </small>
          </div>
        </div>
      </section>
      <section className="admin-section">
        <div className="admin-section-heading">
          <div>
            <h3>Tier management</h3>
            <p>Review plan limits and update individual accounts.</p>
          </div>
        </div>
        <div className="admin-tier-list">
          {tiers.map((tier) => (
            <div className="admin-tier-item" key={tier.id}>
              <strong>{tier.name}</strong>
              <span>
                {tier.maxTripsPerUser ?? "unlimited"} trips /{" "}
                {tier.maxFilesPerTrip ?? "unlimited"} photos /{" "}
                {formatBytes(tier.monthlyUploadBytes)} monthly
              </span>
            </div>
          ))}
        </div>
      </section>
      <section className="admin-section admin-users-section">
        <div className="admin-section-heading">
          <div>
            <h3>User management</h3>
            <p>
              Find an account, review its usage, and explicitly save tier
              changes.
            </p>
          </div>
        </div>
        <form
          className="admin-search"
          onSubmit={async (event) => {
            event.preventDefault();
            try {
              const result = await api.adminUsers(userQuery);
              setAdminUsers(result.users);
              setPendingTierIds({});
              setAdminError("");
            } catch (error) {
              setAdminError(
                error instanceof Error ? error.message : "Unable to find users",
              );
            }
          }}
        >
          <div>
            <h4>Find a user</h4>
            <p>Search by email to review usage and change a tier.</p>
          </div>
          <label>
            Email
            <input
              value={userQuery}
              onChange={(event) => setUserQuery(event.target.value)}
              placeholder="Search by email"
            />
          </label>
          <button type="submit">Search users</button>
        </form>
        {adminUsers.length > 0 ? (
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>User</th>
                  <th>Usage</th>
                  <th>Tier</th>
                </tr>
              </thead>
              <tbody>
                {adminUsers.map((user) => (
                  <tr key={user.id}>
                    <td>
                      <strong>{user.email}</strong>
                      <small>{user.displayName}</small>
                    </td>
                    <td>
                      <div>
                        {user.tripCount} /{" "}
                        {user.tier.maxTripsPerUser ?? "unlimited"} trips
                      </div>
                      <div>
                        {user.photoCount} /{" "}
                        {user.tier.maxFilesPerTrip ?? "unlimited"} photos
                      </div>
                      <div>
                        {formatBytes(user.monthlyUploadedBytes)} /{" "}
                        {formatBytes(user.tier.monthlyUploadBytes)} this month
                      </div>
                    </td>
                    <td>
                      <select
                        value={pendingTierIds[user.id] ?? user.tier.id}
                        aria-label={`Tier for ${user.email}`}
                        onChange={(event) =>
                          setPendingTierIds((current) => ({
                            ...current,
                            [user.id]: event.target.value,
                          }))
                        }
                      >
                        {tiers.map((tier) => (
                          <option key={tier.id} value={tier.id}>
                            {tier.name}
                          </option>
                        ))}
                      </select>
                      <button
                        className="secondary-button admin-update-tier"
                        type="button"
                        disabled={
                          updatingUserId === user.id ||
                          (pendingTierIds[user.id] ?? user.tier.id) ===
                            user.tier.id
                        }
                        onClick={async () => {
                          const nextTierId = pendingTierIds[user.id];
                          if (!nextTierId) return;
                          setUpdatingUserId(user.id);
                          try {
                            const result = await api.assignAdminTier(
                              user.id,
                              nextTierId,
                            );
                            setAdminUsers((current) =>
                              current.map((item) =>
                                item.id === user.id
                                  ? { ...item, tier: result.tier }
                                  : item,
                              ),
                            );
                            setPendingTierIds((current) => {
                              const next = { ...current };
                              delete next[user.id];
                              return next;
                            });
                            setAdminError("");
                          } catch (error) {
                            setAdminError(
                              error instanceof Error
                                ? error.message
                                : "Unable to assign tier",
                            );
                          } finally {
                            setUpdatingUserId(null);
                          }
                        }}
                      >
                        {updatingUserId === user.id
                          ? "Updating..."
                          : "Update tier"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {adminError ? <p className="error">{adminError}</p> : null}
      </section>
      <details className="admin-create">
        <summary>Create tier</summary>
        <form
          className="stack"
          onSubmit={async (event) => {
            event.preventDefault();
            try {
              const tier = await api.createAdminTier({
                slug: tierForm.slug,
                name: tierForm.name,
                maxTripsPerUser: tierForm.trips ? Number(tierForm.trips) : null,
                maxFilesPerTrip: tierForm.photos
                  ? Number(tierForm.photos)
                  : null,
                monthlyUploadBytes: Number(tierForm.bytes),
              });
              setTiers((current) => [...current, tier]);
              setTierForm({
                slug: "",
                name: "",
                trips: "",
                photos: "",
                bytes: "",
              });
              setAdminError("");
            } catch (error) {
              setAdminError(
                error instanceof Error
                  ? error.message
                  : "Unable to create tier",
              );
            }
          }}
        >
          <label>
            Internal ID (slug)
            <input
              placeholder="e.g. partner-2026"
              value={tierForm.slug}
              onChange={(event) =>
                setTierForm({ ...tierForm, slug: event.target.value })
              }
              required
            />
            <small>
              Stable machine-readable identifier. Use lowercase letters,
              numbers, and hyphens.
            </small>
          </label>
          <label>
            Display name
            <input
              placeholder="e.g. Partner"
              value={tierForm.name}
              onChange={(event) =>
                setTierForm({ ...tierForm, name: event.target.value })
              }
              required
            />
          </label>
          <input
            placeholder="max trips (blank = unlimited)"
            type="number"
            value={tierForm.trips}
            onChange={(event) =>
              setTierForm({ ...tierForm, trips: event.target.value })
            }
          />
          <input
            placeholder="max photos (blank = unlimited)"
            type="number"
            value={tierForm.photos}
            onChange={(event) =>
              setTierForm({ ...tierForm, photos: event.target.value })
            }
          />
          <input
            placeholder="monthly upload bytes"
            type="number"
            value={tierForm.bytes}
            onChange={(event) =>
              setTierForm({ ...tierForm, bytes: event.target.value })
            }
            required
          />
          <button type="submit">Create tier</button>
        </form>
      </details>
    </section>
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

type TripBrowserCluster = {
  id: string;
  tripId: string;
  title: string;
  color: string;
  coordinates: [number, number];
  points: TripMapPointResponse[];
  pointCount: number;
};

const tripBrowserPalette = [
  "#23695b",
  "#b54434",
  "#2f6cb3",
  "#8a5a11",
  "#6d5bd0",
  "#16758b",
  "#a43f73",
  "#4f7f2f",
  "#c05a19",
  "#53606f",
];

function formatTripMapDate(value: string | null | undefined): string {
  if (!value) {
    return "No date";
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

function worldPixelForPoint(point: TripMapPointResponse, zoom: number) {
  const scale = 512 * 2 ** zoom;
  const latitude = Math.max(
    -85.05112878,
    Math.min(85.05112878, point.latitude),
  );
  const sinLatitude = Math.sin((latitude * Math.PI) / 180);
  return {
    x: ((point.longitude + 180) / 360) * scale,
    y:
      (0.5 - Math.log((1 + sinLatitude) / (1 - sinLatitude)) / (4 * Math.PI)) *
      scale,
  };
}

function colorForTripId(tripId: string): string {
  let hash = 0;
  for (let index = 0; index < tripId.length; index += 1) {
    hash = (hash * 31 + tripId.charCodeAt(index)) >>> 0;
  }
  return tripBrowserPalette[hash % tripBrowserPalette.length];
}

function offsetForCollision(index: number): [number, number] {
  if (index === 0) {
    return [0, 0];
  }
  const ring = Math.ceil(index / 8);
  const position = (index - 1) % 8;
  const angle = (position / 8) * Math.PI * 2;
  const distance = 10 + (ring - 1) * 6;
  return [
    Math.round(Math.cos(angle) * distance),
    Math.round(Math.sin(angle) * distance),
  ];
}

function clusterTripMapPoints(
  data: TripsMapPointsResponse | null,
  trips: TripResponse[],
  zoom: number,
): TripBrowserCluster[] {
  if (!data) {
    return [];
  }
  const tripTitleById = new Map(trips.map((trip) => [trip.id, trip.title]));
  const tripColorById = new Map(
    data.trips.map((trip, index) => [
      trip.id,
      tripBrowserPalette[index % tripBrowserPalette.length],
    ]),
  );
  const pointsByTrip = new Map<string, TripMapPointResponse[]>();
  for (const point of data.points) {
    const points = pointsByTrip.get(point.tripId) ?? [];
    points.push(point);
    pointsByTrip.set(point.tripId, points);
  }
  const radiusPixels = Math.max(34, 130 - zoom * 8);
  const clusters: TripBrowserCluster[] = [];
  for (const [tripId, points] of pointsByTrip) {
    const tripClusters: Array<{
      points: TripMapPointResponse[];
      pixelX: number;
      pixelY: number;
    }> = [];
    for (const point of points) {
      const pixel = worldPixelForPoint(point, zoom);
      const cluster = tripClusters.find(
        (candidate) =>
          Math.hypot(candidate.pixelX - pixel.x, candidate.pixelY - pixel.y) <=
          radiusPixels,
      );
      if (cluster) {
        cluster.points.push(point);
        cluster.pixelX =
          (cluster.pixelX * (cluster.points.length - 1) + pixel.x) /
          cluster.points.length;
        cluster.pixelY =
          (cluster.pixelY * (cluster.points.length - 1) + pixel.y) /
          cluster.points.length;
      } else {
        tripClusters.push({
          points: [point],
          pixelX: pixel.x,
          pixelY: pixel.y,
        });
      }
    }
    tripClusters.forEach((cluster, index) => {
      const longitude =
        cluster.points.reduce((total, point) => total + point.longitude, 0) /
        cluster.points.length;
      const latitude =
        cluster.points.reduce((total, point) => total + point.latitude, 0) /
        cluster.points.length;
      clusters.push({
        id: `${tripId}:${index}`,
        tripId,
        title: tripTitleById.get(tripId) ?? "Trip",
        color: tripColorById.get(tripId) ?? colorForTripId(tripId),
        coordinates: [longitude, latitude],
        points: cluster.points,
        pointCount: cluster.points.length,
      });
    });
  }
  return clusters;
}

function TripBrowserPanel({
  data,
  endDate,
  error,
  isLoading,
  selectedTripId,
  startDate,
  trips,
  onClearFilters,
  onEndDateChange,
  onSelectTrip,
  onStartDateChange,
}: {
  data: TripsMapPointsResponse | null;
  endDate: string;
  error: string;
  isLoading: boolean;
  selectedTripId: string | null;
  startDate: string;
  trips: TripResponse[];
  onClearFilters: () => void;
  onEndDateChange: (value: string) => void;
  onSelectTrip: (tripId: string) => void;
  onStartDateChange: (value: string) => void;
}) {
  return (
    <>
      <div className="trip-stage-header">
        <div>
          <h2 id="trip-stage-title">Trip Map</h2>
          <p>
            {data
              ? `${data.trips.length} trip${
                  data.trips.length === 1 ? "" : "s"
                } with mapped photos`
              : "Explore trips by place and time"}
          </p>
        </div>
      </div>
      {error ? <p className="error">{error}</p> : null}
      <section className="trip-browser-shell">
        <TripBrowserMap
          data={data}
          isLoading={isLoading}
          selectedTripId={selectedTripId}
          trips={trips}
          onSelectTrip={onSelectTrip}
        />
        <form
          className="trip-browser-filters"
          onSubmit={(event) => event.preventDefault()}
        >
          <label>
            Start
            <input
              type="date"
              value={startDate}
              onChange={(event) => onStartDateChange(event.target.value)}
            />
          </label>
          <label>
            End
            <input
              type="date"
              value={endDate}
              onChange={(event) => onEndDateChange(event.target.value)}
            />
          </label>
          <button
            className="secondary-button"
            type="button"
            onClick={onClearFilters}
            disabled={!startDate && !endDate}
          >
            Clear
          </button>
        </form>
      </section>
    </>
  );
}

function TripBrowserMap({
  data,
  isLoading,
  selectedTripId,
  trips,
  onSelectTrip,
}: {
  data: TripsMapPointsResponse | null;
  isLoading: boolean;
  selectedTripId: string | null;
  trips: TripResponse[];
  onSelectTrip: (tripId: string) => void;
}) {
  const mapNode = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markersRef = useRef<Marker[]>([]);
  const [zoom, setZoom] = useState(1);
  const [openClusterId, setOpenClusterId] = useState<string | null>(null);
  const clusters = useMemo(
    () => clusterTripMapPoints(data, trips, zoom),
    [data, trips, zoom],
  );

  useEffect(() => {
    if (!mapNode.current || mapRef.current) {
      return;
    }
    const map = new maplibregl.Map({
      container: mapNode.current,
      style: configuredMapStyle(),
      center: [0, 18],
      zoom: 1,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    const syncZoom = () => setZoom(map.getZoom());
    map.on("load", syncZoom);
    map.on("zoomend", syncZoom);
    map.on("moveend", syncZoom);
    return () => {
      markersRef.current.forEach((marker) => marker.remove());
      markersRef.current = [];
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !data || data.points.length === 0) {
      return;
    }
    const bounds = new LngLatBounds();
    data.points.forEach((point) =>
      bounds.extend([point.longitude, point.latitude]),
    );
    if (!bounds.isEmpty()) {
      map.fitBounds(bounds, { padding: 64, maxZoom: 7, duration: 500 });
    }
  }, [data]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    markersRef.current.forEach((marker) => marker.remove());
    markersRef.current = [];
    const collisionCounts = new Map<string, number>();
    for (const cluster of clusters) {
      const anchor = document.createElement("div");
      anchor.className =
        cluster.tripId === selectedTripId
          ? "photo-map-marker-anchor selected"
          : "photo-map-marker-anchor";
      if (cluster.id === openClusterId) {
        anchor.classList.add("open");
      }
      const button = document.createElement("button");
      button.type = "button";
      button.className =
        cluster.tripId === selectedTripId
          ? "trip-browser-marker active"
          : "trip-browser-marker";
      button.style.setProperty("--trip-marker-color", cluster.color);
      button.setAttribute(
        "aria-label",
        `Show ${cluster.title}, ${cluster.pointCount} mapped point${
          cluster.pointCount === 1 ? "" : "s"
        }`,
      );
      button.title = cluster.title;
      button.setAttribute("aria-haspopup", "dialog");
      const dot = document.createElement("span");
      dot.className = "trip-browser-marker-dot";
      button.appendChild(dot);

      button.addEventListener("click", (event) => {
        event.stopPropagation();
        setOpenClusterId((current) =>
          current === cluster.id ? null : cluster.id,
        );
      });
      anchor.appendChild(button);
      if (cluster.id === openClusterId) {
        const popupContent = document.createElement("div");
        popupContent.className = "trip-browser-popup";
        const popupButton = document.createElement("button");
        popupButton.type = "button";
        popupButton.className = "trip-browser-popup-title";
        popupButton.textContent = cluster.title;
        popupButton.addEventListener("click", (event) => {
          event.stopPropagation();
          setOpenClusterId(null);
          onSelectTrip(cluster.tripId);
        });
        const popupMeta = document.createElement("span");
        popupMeta.textContent = `${cluster.pointCount} mapped point${
          cluster.pointCount === 1 ? "" : "s"
        }`;
        popupContent.appendChild(popupButton);
        popupContent.appendChild(popupMeta);
        anchor.appendChild(popupContent);
      }
      const projected = map.project(cluster.coordinates);
      const collisionKey = `${Math.round(projected.x / 18)}:${Math.round(
        projected.y / 18,
      )}`;
      const collisionIndex = collisionCounts.get(collisionKey) ?? 0;
      collisionCounts.set(collisionKey, collisionIndex + 1);
      markersRef.current.push(
        new maplibregl.Marker({
          anchor: "center",
          element: anchor,
          offset: offsetForCollision(collisionIndex),
        })
          .setLngLat(cluster.coordinates)
          .addTo(map),
      );
    }
    return () => {
      markersRef.current.forEach((marker) => marker.remove());
      markersRef.current = [];
    };
  }, [clusters, onSelectTrip, openClusterId, selectedTripId]);

  const selectedTripSummary =
    data?.trips.find((trip) => trip.id === selectedTripId) ??
    data?.trips[0] ??
    null;

  return (
    <div className="story-map-panel trip-browser-map-panel">
      <div className="story-map-shell local-map-shell">
        <div ref={mapNode} className="story-map" />
        {isLoading ? (
          <div className="map-empty-state">
            <strong>Loading trips</strong>
            <span>Preparing mapped photos.</span>
          </div>
        ) : !data || data.points.length === 0 ? (
          <div className="map-empty-state">
            <strong>No mapped trips</strong>
            <span>Add photos with location data or widen the date filter.</span>
          </div>
        ) : null}
      </div>
      <div className="trip-browser-summary">
        {selectedTripSummary ? (
          <div>
            <strong>{selectedTripSummary.title}</strong>
            <span>
              {formatTripMapDate(selectedTripSummary.firstCapturedAt)} -{" "}
              {formatTripMapDate(selectedTripSummary.lastCapturedAt)}
            </span>
          </div>
        ) : (
          <div>
            <strong>Trip map</strong>
            <span>Zoom into a region to split trips into local markers.</span>
          </div>
        )}
        <span>
          {data?.points.length ?? 0} point
          {data?.points.length === 1 ? "" : "s"}
        </span>
      </div>
    </div>
  );
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
  onDeleteStop,
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
  onDeleteStop?: (stopId: string) => Promise<void>;
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
  const dayColorMap = useMemo(() => storyDayColorMap(model), [model]);
  const selectedStop = filteredModel.stops.find(
    (stop) => stop.id === state.selectedStopId,
  );
  const timelineStopsById = useMemo(
    () =>
      new Map(
        reconstruction?.days.flatMap((day) =>
          day.stops.map((stop) => [stop.id, stop] as const),
        ) ?? [],
      ),
    [reconstruction?.days],
  );
  const selectedMedia = filteredModel.media.find(
    (item) => item.id === state.selectedMediaId,
  );
  const activeStopRefs = useRef<Record<string, HTMLElement | null>>({});
  const reducedMotion = useReducedMotion();
  const [galleryMediaId, setGalleryMediaId] = useState<string | null>(null);
  const [galleryPhotoIds, setGalleryPhotoIds] = useState<string[] | null>(null);
  const [galleryScopedPhotos, setGalleryScopedPhotos] = useState<
    GalleryPhoto[] | null
  >(null);
  const [editToolsStopId, setEditToolsStopId] = useState<string | null>(null);
  const [openStopActionsId, setOpenStopActionsId] = useState<string | null>(
    null,
  );
  const [editingStopId, setEditingStopId] = useState<string | null>(null);
  const [stopTitleDraft, setStopTitleDraft] = useState("");
  const [renameStopError, setRenameStopError] = useState("");
  const [savingStopId, setSavingStopId] = useState<string | null>(null);
  const [pendingDeleteStopId, setPendingDeleteStopId] = useState<string | null>(
    null,
  );
  const [editingNoteKey, setEditingNoteKey] = useState<string | null>(null);
  const [openDayActionsId, setOpenDayActionsId] = useState<string | null>(null);
  const [pendingTimelineDaySelection, setPendingTimelineDaySelection] =
    useState<{
      dayId: string;
      previousSelectedDayId: string | null;
    } | null>(null);
  const dayStopTransitionTimerRef = useRef<number | null>(null);
  const storyStateRef = useRef(state);
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
  const photoRollScrollRef = useRef<HTMLDivElement | null>(null);
  const photoRollScrollTopRef = useRef(0);
  const photoRollContentKeyRef = useRef<string | null>(null);
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
  const [areaEditingMode, setAreaEditingMode] = useState<
    "rename" | "manage" | null
  >(null);
  const [openAreaActionsId, setOpenAreaActionsId] = useState<string | null>(
    null,
  );
  const [areaTitleDraft, setAreaTitleDraft] = useState("");
  const [areaEditError, setAreaEditError] = useState("");
  const [savingAreaActionKey, setSavingAreaActionKey] = useState<string | null>(
    null,
  );
  const [pendingTimelineAction, setPendingTimelineAction] = useState<
    string | null
  >(null);
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
  const photoRollContentKey = `${photoProjectionScope}:day:${
    activePhotoDayId ?? "none"
  }`;
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

  useLayoutEffect(() => {
    if (!isPhotoRollVisible) {
      photoRollScrollTopRef.current = 0;
      photoRollContentKeyRef.current = null;
      return;
    }
    if (photoRollContentKeyRef.current === photoRollContentKey) {
      return;
    }
    photoRollContentKeyRef.current = photoRollContentKey;
    photoRollScrollTopRef.current = 0;
    const photoRoll = photoRollScrollRef.current;
    if (!photoRoll) {
      return;
    }
    photoRoll.scrollTop = 0;
  }, [isPhotoRollVisible, photoRollContentKey]);

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
    const normalizedState = normalizeStoryMapState(state, model);
    if (normalizedState !== state) {
      onStateChange(normalizedState);
    }
  }, [model, onStateChange, state]);

  useEffect(() => {
    if (displayMobilePane !== "timeline" || !state.selectedStopId) {
      return;
    }
    const element = activeStopRefs.current[state.selectedStopId];
    if (!element) {
      return;
    }
    const frameId = window.requestAnimationFrame(() => {
      element.scrollIntoView({
        block: "center",
        behavior: reducedMotion ? "auto" : "smooth",
      });
    });
    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [displayMobilePane, reducedMotion, state.selectedStopId]);

  useEffect(
    () => () => {
      if (dayStopTransitionTimerRef.current !== null) {
        window.clearTimeout(dayStopTransitionTimerRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    storyStateRef.current = state;
  }, [state]);

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
    return true;
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
    setExpandedMapAreaId(null);
    if (dayStopTransitionTimerRef.current !== null) {
      window.clearTimeout(dayStopTransitionTimerRef.current);
      dayStopTransitionTimerRef.current = null;
    }
    if (!firstStop) {
      onStateChange(selectStoryDay(state, dayId));
      return;
    }
    onStateChange(selectStoryDay(state, dayId));
    dayStopTransitionTimerRef.current = window.setTimeout(() => {
      const currentState = storyStateRef.current;
      if (
        currentState.viewMode === "DAY" &&
        currentState.selectedDayId === dayId &&
        !currentState.selectedStopId
      ) {
        onStateChange(selectStoryStop(currentState, firstStop.id, dayId));
      }
      dayStopTransitionTimerRef.current = null;
    }, 1000);
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

  function areaVisitStopFromReconstructionStop(
    stop: ReconstructionStopResponse,
    membershipSortOrder: number,
  ): AreaVisitStopResponse {
    return {
      id: stop.id,
      position: stop.position,
      title: stop.title,
      startsAt: stop.startsAt,
      endsAt: stop.endsAt,
      placeName: stop.placeName,
      latitude: stop.latitude,
      longitude: stop.longitude,
      membershipSource: "user_edited",
      membershipConfidence: 1,
      membershipSortOrder,
      membershipUserLocked: true,
    };
  }

  function areaVisitStopById(
    day: ReconstructionDayResponse,
  ): Map<string, AreaVisitStopResponse> {
    return new Map(
      day.stops.map((stop, index) => [
        stop.id,
        areaVisitStopFromReconstructionStop(stop, index + 1),
      ]),
    );
  }

  function updateAreaVisitsForDay(
    dayId: string,
    update: (current: AreaVisitsResponse | undefined) => AreaVisitsResponse,
  ) {
    setAreaVisitsByDay((current) => ({
      ...current,
      [dayId]: update(current[dayId]),
    }));
  }

  function optimisticCreateAreaVisit(
    day: ReconstructionDayResponse,
    stopIds: string[],
    title: string,
  ) {
    const stopLookup = areaVisitStopById(day);
    const stopIdSet = new Set(stopIds);
    const selectedStops = day.stops
      .filter((stop) => stopIdSet.has(stop.id))
      .map((stop, index) =>
        areaVisitStopFromReconstructionStop(stop, index + 1),
      );
    if (selectedStops.length === 0) {
      return;
    }
    const now = new Date().toISOString();
    updateAreaVisitsForDay(day.id, (current) => {
      const areas = current?.areas ?? [];
      const optimisticArea: AreaVisitResponse = {
        id: `optimistic-area:${day.id}:${stopIds.join("-")}`,
        tripId: current?.tripId ?? tripId ?? "",
        dayId: day.id,
        reconstructionRunId:
          current?.sourceReconstructionRunId ??
          reconstruction?.latestRun?.id ??
          "",
        sortOrder: areas.length + 1,
        title,
        startsAt: selectedStops[0]?.startsAt ?? now,
        endsAt: selectedStops[selectedStops.length - 1]?.endsAt ?? now,
        latitude: selectedStops[0]?.latitude ?? null,
        longitude: selectedStops[0]?.longitude ?? null,
        confidence: 1,
        source: "user_edited",
        algorithmVersion: "pending-ui",
        userLocked: true,
        bounds: {},
        diagnostics: { pending: true },
        stops: selectedStops,
      };
      const fallbackStandaloneStops = Array.from(stopLookup.values());
      return {
        tripId: current?.tripId ?? tripId ?? "",
        dayId: day.id,
        sourceReconstructionRunId:
          current?.sourceReconstructionRunId ??
          reconstruction?.latestRun?.id ??
          null,
        areas: [...areas, optimisticArea],
        standaloneStops: (
          current?.standaloneStops ?? fallbackStandaloneStops
        ).filter((stop) => !stopIdSet.has(stop.id)),
      };
    });
  }

  function optimisticRenameAreaVisit(area: AreaVisitResponse, title: string) {
    updateAreaVisitsForDay(area.dayId, (current) => ({
      ...(current ?? {
        tripId: area.tripId,
        dayId: area.dayId,
        sourceReconstructionRunId: area.reconstructionRunId,
        standaloneStops: [],
      }),
      areas: (current?.areas ?? [area]).map((candidate) =>
        candidate.id === area.id ? { ...candidate, title } : candidate,
      ),
    }));
  }

  function optimisticAddStopToArea(
    day: ReconstructionDayResponse,
    area: AreaVisitResponse,
    stopId: string,
  ) {
    const stopLookup = areaVisitStopById(day);
    const stopToAdd = stopLookup.get(stopId);
    if (!stopToAdd) {
      return;
    }
    updateAreaVisitsForDay(day.id, (current) => {
      const currentArea = current?.areas.find(
        (candidate) => candidate.id === area.id,
      );
      const nextStopIds = new Set([
        ...(currentArea?.stops ?? area.stops).map((stop) => stop.id),
        stopId,
      ]);
      const orderedStops = day.stops
        .filter((stop) => nextStopIds.has(stop.id))
        .map((stop, index) =>
          areaVisitStopFromReconstructionStop(stop, index + 1),
        );
      return {
        ...(current ?? {
          tripId: area.tripId,
          dayId: day.id,
          sourceReconstructionRunId: area.reconstructionRunId,
          standaloneStops: [],
        }),
        areas: (current?.areas ?? [area]).map((candidate) =>
          candidate.id === area.id
            ? { ...candidate, stops: orderedStops }
            : candidate,
        ),
        standaloneStops: (current?.standaloneStops ?? []).filter(
          (stop) => stop.id !== stopId,
        ),
      };
    });
  }

  function optimisticRemoveStopFromArea(
    day: ReconstructionDayResponse,
    area: AreaVisitResponse,
    stopId: string,
  ) {
    const stopLookup = areaVisitStopById(day);
    const stopToRemove = stopLookup.get(stopId);
    if (!stopToRemove) {
      return;
    }
    updateAreaVisitsForDay(day.id, (current) => {
      const standaloneStops = [
        ...(current?.standaloneStops ?? []),
        stopToRemove,
      ].sort(
        (left, right) =>
          day.stops.findIndex((stop) => stop.id === left.id) -
          day.stops.findIndex((stop) => stop.id === right.id),
      );
      return {
        ...(current ?? {
          tripId: area.tripId,
          dayId: day.id,
          sourceReconstructionRunId: area.reconstructionRunId,
          standaloneStops: [],
        }),
        areas: (current?.areas ?? [area]).map((candidate) =>
          candidate.id === area.id
            ? {
                ...candidate,
                stops: candidate.stops.filter((stop) => stop.id !== stopId),
              }
            : candidate,
        ),
        standaloneStops,
      };
    });
  }

  function optimisticDeleteAreaVisit(area: AreaVisitResponse) {
    setAreaVisitsByDay((current) => {
      const dayAreaVisits = current[area.dayId];
      if (!dayAreaVisits) {
        return current;
      }
      return {
        ...current,
        [area.dayId]: {
          ...dayAreaVisits,
          areas: dayAreaVisits.areas.filter(
            (candidate) => candidate.id !== area.id,
          ),
          standaloneStops: [
            ...dayAreaVisits.standaloneStops,
            ...area.stops,
          ].sort((left, right) => left.position - right.position),
        },
      };
    });
  }

  function areaMetrics(stops: ReconstructionStopResponse[]) {
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
    return { stopCount: stops.length, photoCount, travelerCount };
  }

  function areaSummary(stops: ReconstructionStopResponse[]): string {
    const { stopCount, photoCount, travelerCount } = areaMetrics(stops);
    return `${stopCount} stops · ${photoCount} photos · ${travelerCount} travelers`;
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
    setAreaEditingMode(null);
    setOpenAreaActionsId(null);
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
    const previousAreaVisitsByDay = areaVisitsByDay;
    setIsCreatingArea(true);
    setCreateAreaError("");
    setPendingTimelineAction("Creating area...");
    optimisticCreateAreaVisit(day, selectedAreaStopIds, title);
    try {
      await onCreateAreaVisit(day.id, selectedAreaStopIds, title);
      cancelAreaSelection();
    } catch (error) {
      setAreaVisitsByDay(previousAreaVisitsByDay);
      setCreateAreaError(messageFrom(error));
    } finally {
      setIsCreatingArea(false);
      setPendingTimelineAction(null);
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

  function startEditingArea(
    area: AreaVisitResponse,
    mode: "rename" | "manage",
  ) {
    setEditingAreaId(area.id);
    setAreaEditingMode(mode);
    setAreaTitleDraft(displayAreaTitle(area));
    setAreaEditError("");
  }

  async function saveAreaTitle(area: AreaVisitResponse) {
    const nextTitle = areaTitleDraft.trim();
    if (!onRenameAreaVisit || !nextTitle) {
      return;
    }
    const previousAreaVisitsByDay = areaVisitsByDay;
    setSavingAreaActionKey(`rename:${area.id}`);
    setAreaEditError("");
    setPendingTimelineAction("Renaming area...");
    optimisticRenameAreaVisit(area, nextTitle);
    try {
      await onRenameAreaVisit(area.id, nextTitle);
      setEditingAreaId(null);
      setAreaEditingMode(null);
      setAreaTitleDraft("");
    } catch (error) {
      setAreaVisitsByDay(previousAreaVisitsByDay);
      setAreaEditError(messageFrom(error));
    } finally {
      setSavingAreaActionKey(null);
      setPendingTimelineAction(null);
    }
  }

  async function addStopToArea(
    day: ReconstructionDayResponse,
    area: AreaVisitResponse,
    stopId: string,
  ) {
    if (!onAddAreaVisitStop) {
      return;
    }
    const previousAreaVisitsByDay = areaVisitsByDay;
    const key = `add:${area.id}:${stopId}`;
    setSavingAreaActionKey(key);
    setAreaEditError("");
    setPendingTimelineAction("Adding stop...");
    optimisticAddStopToArea(day, area, stopId);
    try {
      await onAddAreaVisitStop(area.id, stopId);
    } catch (error) {
      setAreaVisitsByDay(previousAreaVisitsByDay);
      setAreaEditError(messageFrom(error));
    } finally {
      setSavingAreaActionKey(null);
      setPendingTimelineAction(null);
    }
  }

  async function removeStopFromArea(
    day: ReconstructionDayResponse,
    area: AreaVisitResponse,
    stopId: string,
  ) {
    if (!onRemoveAreaVisitStop) {
      return;
    }
    const previousAreaVisitsByDay = areaVisitsByDay;
    const key = `remove:${area.id}:${stopId}`;
    setSavingAreaActionKey(key);
    setAreaEditError("");
    setPendingTimelineAction("Removing stop...");
    optimisticRemoveStopFromArea(day, area, stopId);
    try {
      await onRemoveAreaVisitStop(area.id, stopId);
    } catch (error) {
      setAreaVisitsByDay(previousAreaVisitsByDay);
      setAreaEditError(messageFrom(error));
    } finally {
      setSavingAreaActionKey(null);
      setPendingTimelineAction(null);
    }
  }

  async function deleteArea(area: AreaVisitResponse) {
    if (!onDeleteAreaVisit) {
      return;
    }
    const previousAreaVisitsByDay = areaVisitsByDay;
    const key = `delete:${area.id}`;
    setSavingAreaActionKey(key);
    setAreaEditError("");
    setPendingTimelineAction("Deleting area...");
    optimisticDeleteAreaVisit(area);
    try {
      await onDeleteAreaVisit(area.id);
      setEditingAreaId(null);
      setAreaEditingMode(null);
      setAreaTitleDraft("");
    } catch (error) {
      setAreaVisitsByDay(previousAreaVisitsByDay);
      setEditingAreaId(area.id);
      setAreaEditingMode("manage");
      setAreaEditError(messageFrom(error));
    } finally {
      setSavingAreaActionKey(null);
      setPendingTimelineAction(null);
    }
  }

  function startRenamingStop(
    stop: ReconstructionResponse["days"][number]["stops"][number],
  ) {
    setEditingStopId(stop.id);
    setStopTitleDraft(displayStopTitle(stop));
    setRenameStopError("");
  }

  function startEditingNote(key: string, note: string | null | undefined) {
    setEditingNoteKey(key);
    setNoteDraft(note ?? "");
    setNoteError("");
  }

  function closeStopEditing() {
    setEditToolsStopId(null);
    setOpenStopActionsId(null);
    setEditingStopId(null);
    setStopTitleDraft("");
    setRenameStopError("");
    setEditingNoteKey(null);
    setNoteDraft("");
    setNoteError("");
    setMergeStopError("");
    setMergePickerStopId(null);
    setPendingMergeKey(null);
    setSplitStopId(null);
    setSplitStopError("");
    setPendingSplitKey(null);
    setPendingDeleteStopId(null);
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
      closeStopEditing();
    } catch (error) {
      setRenameStopError(messageFrom(error));
    } finally {
      setSavingStopId(null);
    }
  }

  async function deleteTimelineStop(
    stop: ReconstructionStopResponse,
    dayId: string,
  ) {
    if (!onDeleteStop) {
      return;
    }
    if (pendingDeleteStopId !== stop.id) {
      setPendingDeleteStopId(stop.id);
      return;
    }
    setSavingStopId(stop.id);
    setPendingTimelineAction("Removing stop from timeline...");
    try {
      await onDeleteStop(stop.id);
      onStateChange(selectStoryDay(state, dayId));
      setEditToolsStopId(null);
      setPendingDeleteStopId(null);
    } catch (error) {
      setRenameStopError(messageFrom(error));
    } finally {
      setSavingStopId(null);
      setPendingTimelineAction(null);
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
      if (kind === "stop") {
        closeStopEditing();
      } else {
        setEditingNoteKey(null);
        setNoteDraft("");
      }
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
    setPendingTimelineAction("Merging stops...");
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
      setPendingTimelineAction(null);
    }
  }

  function orderedStopMedia(stop: ReconstructionStopResponse) {
    return stop.moments.flatMap((moment) => moment.media);
  }

  function timelineStopTimeLabel(stop: ReconstructionStopResponse): {
    dateTime: string;
    labels: string[];
  } {
    const startsAt = formatTimelineStopTime(
      stop.startsAt,
      stop.startsAtLocal ?? null,
      timezoneId,
    );
    const endsAt = formatTimelineStopTime(
      stop.endsAt,
      stop.endsAtLocal ?? null,
      timezoneId,
    );
    return {
      dateTime: stop.startsAt,
      labels: startsAt === endsAt ? [startsAt] : [startsAt, endsAt],
    };
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
    setPendingTimelineAction("Splitting stop...");
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
      setPendingTimelineAction(null);
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
  const selectedStopMetrics =
    selectedStopDetail && !isCollapsedAreaSelected
      ? {
          photoCount: selectedStopDetail.mediaCount,
          travelerCount: selectedStopDetail.contributorCount,
        }
      : null;
  const selectedDayMetrics =
    !selectedStopDetail && activeDay
      ? {
          stopCount: activeDay.stops.length,
          photoCount: activeDay.stops.reduce(
            (total, stop) => total + stop.mediaCount,
            0,
          ),
        }
      : null;
  const selectedNote =
    (isCollapsedAreaSelected ? "" : selectedStopDetail?.note?.trim()) ||
    activeDay?.note?.trim() ||
    "";
  const activeTimelineDay = activeDay ?? story.days[0] ?? null;
  const visualTimelineDayId =
    pendingTimelineDaySelection &&
    state.selectedDayId === pendingTimelineDaySelection.previousSelectedDayId
      ? pendingTimelineDaySelection.dayId
      : (activeTimelineDay?.id ?? null);
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
            {selectedStopMetrics ? (
              <div className="story-selected-stop-metrics">
                <span aria-label={`${selectedStopMetrics.photoCount} photos`}>
                  <TimelineMetricIcon name="camera" />
                  {selectedStopMetrics.photoCount}
                </span>
                <span
                  aria-label={`${selectedStopMetrics.travelerCount} travelers`}
                >
                  <TimelineMetricIcon name="travelers" />
                  {selectedStopMetrics.travelerCount}
                </span>
              </div>
            ) : selectedDayMetrics ? (
              <div className="story-selected-stop-metrics">
                <span aria-label={`${selectedDayMetrics.stopCount} stops`}>
                  <TimelineMetricIcon name="stops" />
                  {selectedDayMetrics.stopCount}
                </span>
                <span aria-label={`${selectedDayMetrics.photoCount} photos`}>
                  <TimelineMetricIcon name="camera" />
                  {selectedDayMetrics.photoCount}
                </span>
              </div>
            ) : (
              <p>{selectedStopSummary}</p>
            )}
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
        <section className="story-timeline" aria-label="Chronological timeline">
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
                const isActive = visualTimelineDayId === day.id;
                return (
                  <button
                    type="button"
                    className={isActive ? "active" : ""}
                    aria-pressed={isActive}
                    key={day.id}
                    onClick={() => {
                      setPendingTimelineDaySelection({
                        dayId: day.id,
                        previousSelectedDayId: state.selectedDayId,
                      });
                      onStateChange(selectStoryDay(state, day.id));
                    }}
                  >
                    <span>
                      {dateParts.weekday}
                      {dateParts.day ? ` ${dateParts.day}` : ""}
                    </span>
                  </button>
                );
              })}
            </div>
          ) : null}
          {pendingTimelineAction ? (
            <div className="timeline-pending-status" role="status">
              <span className="button-spinner" aria-hidden="true" />
              <span>{pendingTimelineAction}</span>
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
                  style={
                    {
                      "--timeline-day-color":
                        dayColorMap.get(day.id) ?? storyDayColors[0],
                    } as CSSProperties
                  }
                >
                  <div className="timeline-day-heading">
                    <button
                      type="button"
                      className="timeline-day-button"
                      onClick={() =>
                        onStateChange(selectStoryDay(state, day.id))
                      }
                    >
                      <span>{storyDayDateLabel(day)}</span>
                    </button>
                    {(onCreateAreaVisit || onSetDayNote) && (
                      <div className="timeline-day-actions">
                        <button
                          type="button"
                          className="timeline-day-actions-trigger"
                          aria-expanded={openDayActionsId === day.id}
                          aria-haspopup="menu"
                          onClick={() =>
                            setOpenDayActionsId((current) =>
                              current === day.id ? null : day.id,
                            )
                          }
                        >
                          Day Actions
                          <TimelineChevron
                            direction={
                              openDayActionsId === day.id ? "up" : "down"
                            }
                          />
                        </button>
                        {openDayActionsId === day.id ? (
                          <div
                            className="timeline-day-actions-menu"
                            role="menu"
                          >
                            {onCreateAreaVisit ? (
                              <button
                                type="button"
                                role="menuitem"
                                disabled={
                                  areaSelectionDayId !== day.id &&
                                  (day.stops.length < 3 ||
                                    !areaVisitsByDay[day.id])
                                }
                                onClick={() => {
                                  setOpenDayActionsId(null);
                                  if (areaSelectionDayId === day.id) {
                                    cancelAreaSelection();
                                  } else {
                                    startAreaSelection(day);
                                  }
                                }}
                              >
                                {areaSelectionDayId === day.id
                                  ? "Cancel area"
                                  : "Create area"}
                              </button>
                            ) : null}
                            {onSetDayNote ? (
                              <button
                                type="button"
                                role="menuitem"
                                onClick={() => {
                                  setOpenDayActionsId(null);
                                  startEditingNote(`day:${day.id}`, day.note);
                                }}
                              >
                                {day.note ? "Edit note" : "Add note"}
                              </button>
                            ) : null}
                          </div>
                        ) : null}
                      </div>
                    )}
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
                    const stopIndexInDay = day.stops.findIndex(
                      (dayStop) => dayStop.id === stop.id,
                    );
                    const isManagingStop = editToolsStopId === stop.id;
                    const isAreaSelectionMode = areaSelectionDayId === day.id;
                    const isAreaStopSelected =
                      isAreaSelectionMode &&
                      selectedAreaStopIds.includes(stop.id);
                    const canEditStop =
                      !isAreaSelectionMode &&
                      (onRenameStop ||
                        onSetStopNote ||
                        onMergeStops ||
                        onSplitStop ||
                        onDeleteStop);
                    const canManageStop = Boolean(
                      onMergeStops || onSplitStop || onDeleteStop,
                    );
                    const isEditingPanel =
                      isManagingStop ||
                      editingStopId === stop.id ||
                      editingNoteKey === `stop:${stop.id}`;
                    const isStopActionsOpen = openStopActionsId === stop.id;
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
                    const stopTime = timelineStopTimeLabel(stop);
                    const areaContext = areaForStop(day, stop.id);
                    const areaMetricValues = areaContext
                      ? areaMetrics(areaContext.stops)
                      : null;
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
                    const featuredStopMedia =
                      stopMedia.find(
                        (media) => media.thumbnailUrl ?? media.previewUrl,
                      ) ?? stopMedia[0];
                    const featuredStopImage =
                      featuredStopMedia?.thumbnailUrl ??
                      featuredStopMedia?.previewUrl ??
                      null;
                    return (
                      <div
                        className={`${
                          areaContext
                            ? `timeline-stop-stack in-area ${
                                isFirstAreaStop ? "area-start" : ""
                              } ${isLastAreaStop ? "area-end" : ""} ${
                                isFirstAreaStop && stopIndexInDay > 0
                                  ? "has-previous-stop"
                                  : ""
                              }`
                            : "timeline-stop-stack"
                        } ${isStopActionsOpen ? "stop-actions-open" : ""} ${
                          openAreaActionsId === areaContext?.area.id
                            ? "area-actions-open"
                            : ""
                        }`}
                        key={stop.id}
                      >
                        {areaContext && isFirstAreaStop ? (
                          <div
                            className={`timeline-area-heading ${
                              openAreaActionsId === areaContext.area.id
                                ? "area-actions-open"
                                : ""
                            }`}
                          >
                            <div className="timeline-area-heading-main">
                              <span className="timeline-area-kicker">
                                Area {areaContext.area.sortOrder}
                              </span>
                              <strong>
                                {displayAreaTitle(areaContext.area)}
                              </strong>
                              {areaMetricValues ? (
                                <div className="timeline-area-metrics">
                                  <span
                                    aria-label={`${areaMetricValues.stopCount} stops`}
                                  >
                                    <TimelineMetricIcon name="stops" />
                                    {areaMetricValues.stopCount}
                                  </span>
                                  <span
                                    aria-label={`${areaMetricValues.photoCount} photos`}
                                  >
                                    <TimelineMetricIcon name="camera" />
                                    {areaMetricValues.photoCount}
                                  </span>
                                  <span
                                    aria-label={`${areaMetricValues.travelerCount} travelers`}
                                  >
                                    <TimelineMetricIcon name="travelers" />
                                    {areaMetricValues.travelerCount}
                                  </span>
                                </div>
                              ) : null}
                            </div>
                            {canEditArea ? (
                              <div className="timeline-stop-actions-menu-wrap">
                                <button
                                  type="button"
                                  className="timeline-icon-button"
                                  aria-expanded={
                                    openAreaActionsId === areaContext.area.id
                                  }
                                  aria-haspopup="menu"
                                  aria-label={`Actions for ${displayAreaTitle(areaContext.area)}`}
                                  title="Area actions"
                                  onClick={() => {
                                    if (
                                      openAreaActionsId === areaContext.area.id
                                    ) {
                                      setOpenAreaActionsId(null);
                                    } else {
                                      setOpenAreaActionsId(areaContext.area.id);
                                    }
                                  }}
                                >
                                  <TimelineMoreIcon />
                                </button>
                                {openAreaActionsId === areaContext.area.id ? (
                                  <div
                                    className="timeline-stop-actions-menu"
                                    role="menu"
                                  >
                                    <button
                                      type="button"
                                      role="menuitem"
                                      disabled={!onRenameAreaVisit}
                                      onClick={() => {
                                        setOpenAreaActionsId(null);
                                        startEditingArea(
                                          areaContext.area,
                                          "rename",
                                        );
                                      }}
                                    >
                                      Rename area
                                    </button>
                                    <button
                                      type="button"
                                      role="menuitem"
                                      disabled={
                                        !onAddAreaVisitStop &&
                                        !onRemoveAreaVisitStop
                                      }
                                      onClick={() => {
                                        setOpenAreaActionsId(null);
                                        if (
                                          editingAreaId ===
                                            areaContext.area.id &&
                                          areaEditingMode === "manage"
                                        ) {
                                          setEditingAreaId(null);
                                          setAreaEditingMode(null);
                                          setAreaEditError("");
                                        } else {
                                          startEditingArea(
                                            areaContext.area,
                                            "manage",
                                          );
                                        }
                                      }}
                                    >
                                      Manage area
                                    </button>
                                    <button
                                      type="button"
                                      role="menuitem"
                                      className="danger"
                                      disabled={!onDeleteAreaVisit}
                                      onClick={() => {
                                        setOpenAreaActionsId(null);
                                        void deleteArea(areaContext.area);
                                      }}
                                    >
                                      Delete area
                                    </button>
                                  </div>
                                ) : null}
                              </div>
                            ) : null}
                            {editingAreaId === areaContext.area.id ? (
                              <div className="timeline-area-edit-panel">
                                {areaEditingMode === "rename" &&
                                onRenameAreaVisit ? (
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
                                          setAreaEditingMode(null);
                                          setAreaTitleDraft("");
                                          setAreaEditError("");
                                        }}
                                      >
                                        <TimelineActionIcon name="x" />
                                      </button>
                                    </div>
                                  </form>
                                ) : null}
                                {areaEditingMode === "manage" ? (
                                  <div className="timeline-edit-context">
                                    <strong>
                                      Manage{" "}
                                      {displayAreaTitle(areaContext.area)}
                                    </strong>
                                  </div>
                                ) : null}
                                {areaEditingMode === "manage" &&
                                onAddAreaVisitStop &&
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
                                            day,
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
                                            day,
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
                                {areaEditingMode === "manage" &&
                                onRemoveAreaVisitStop ? (
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
                                              day,
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
                          <span
                            className="timeline-stop-marker"
                            aria-hidden="true"
                          >
                            {displayStopPosition(stop)}
                          </span>
                          <div className="timeline-stop-card">
                            <time
                              className="timeline-stop-time"
                              dateTime={stopTime.dateTime}
                            >
                              {stopTime.labels.map((label) => (
                                <span key={label}>{label}</span>
                              ))}
                            </time>
                            <div
                              className="timeline-stop-photo"
                              aria-hidden="true"
                            >
                              {featuredStopImage ? (
                                <img
                                  src={featuredStopImage}
                                  alt=""
                                  loading="lazy"
                                />
                              ) : (
                                <span>{displayStopPosition(stop)}</span>
                              )}
                            </div>
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
                                  <span className="timeline-stop-title">
                                    {displayStopTitle(stop)}
                                  </span>
                                </span>
                                <small className="timeline-stop-metrics">
                                  <span>
                                    <TimelineMetricIcon name="camera" />
                                    {stop.mediaCount}
                                  </span>
                                  <span>
                                    <TimelineMetricIcon name="travelers" />
                                    {stop.contributorCount}
                                  </span>
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
                                  <div className="timeline-stop-actions-menu-wrap">
                                    <button
                                      type="button"
                                      className="timeline-icon-button"
                                      aria-expanded={isStopActionsOpen}
                                      aria-haspopup="menu"
                                      aria-label={`Actions for ${displayStopTitle(stop)}`}
                                      title="Stop actions"
                                      onClick={() => {
                                        if (openStopActionsId === stop.id) {
                                          setOpenStopActionsId(null);
                                        } else if (isEditingPanel) {
                                          closeStopEditing();
                                        } else {
                                          setOpenStopActionsId(stop.id);
                                        }
                                      }}
                                    >
                                      <TimelineMoreIcon />
                                    </button>
                                    {isStopActionsOpen ? (
                                      <div
                                        className="timeline-stop-actions-menu"
                                        role="menu"
                                      >
                                        <button
                                          type="button"
                                          role="menuitem"
                                          disabled={!onRenameStop}
                                          onClick={() => {
                                            setOpenStopActionsId(null);
                                            setEditToolsStopId(null);
                                            setEditingNoteKey(null);
                                            startRenamingStop(stop);
                                          }}
                                        >
                                          Rename stop
                                        </button>
                                        <button
                                          type="button"
                                          role="menuitem"
                                          disabled={!onSetStopNote}
                                          onClick={() => {
                                            setOpenStopActionsId(null);
                                            setEditToolsStopId(null);
                                            setEditingStopId(null);
                                            setStopTitleDraft("");
                                            setRenameStopError("");
                                            startEditingNote(
                                              `stop:${stop.id}`,
                                              stop.note,
                                            );
                                          }}
                                        >
                                          Add note
                                        </button>
                                        <button
                                          type="button"
                                          role="menuitem"
                                          disabled={!canManageStop}
                                          onClick={() => {
                                            setOpenStopActionsId(null);
                                            setEditToolsStopId(stop.id);
                                            setEditingStopId(null);
                                            setStopTitleDraft("");
                                            setRenameStopError("");
                                            setEditingNoteKey(null);
                                            setNoteDraft("");
                                            setNoteError("");
                                            setMergeStopError("");
                                            setMergePickerStopId(null);
                                            setPendingMergeKey(null);
                                            setSplitStopId(null);
                                            setSplitStopError("");
                                            setPendingSplitKey(null);
                                            setPendingDeleteStopId(null);
                                          }}
                                        >
                                          Manage stop
                                        </button>
                                      </div>
                                    ) : null}
                                  </div>
                                ) : null}
                              </div>
                            </div>
                            {stop.note && !isEditingPanel ? (
                              <p className="timeline-note-preview">
                                {stop.note}
                              </p>
                            ) : null}
                            {isEditingPanel ? (
                              <div className="timeline-stop-edit-panel">
                                {isManagingStop ? (
                                  <div className="timeline-edit-context">
                                    <strong>
                                      Manage {displayStopTitle(stop)}
                                    </strong>
                                  </div>
                                ) : null}
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
                                {isManagingStop &&
                                ((onMergeStops && mergeCandidates.length > 0) ||
                                  (onSplitStop && stopMedia.length > 1) ||
                                  onDeleteStop) ? (
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
                                    {onDeleteStop ? (
                                      <button
                                        type="button"
                                        className={
                                          pendingDeleteStopId === stop.id
                                            ? "timeline-tool-button danger pending"
                                            : "timeline-tool-button danger"
                                        }
                                        disabled={savingStopId === stop.id}
                                        onClick={() =>
                                          void deleteTimelineStop(stop, day.id)
                                        }
                                      >
                                        {pendingDeleteStopId === stop.id
                                          ? "Confirm remove"
                                          : "Remove stop"}
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
                                {isManagingStop &&
                                canMergeHere &&
                                mergeSourceStop ? (
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
                                {isManagingStop &&
                                onMergeStops &&
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
                                {isManagingStop &&
                                onSplitStop &&
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
            <div
              ref={photoRollScrollRef}
              className="story-photo-roll"
              aria-label="Photos by stop"
              onScroll={(event) => {
                photoRollScrollTopRef.current = event.currentTarget.scrollTop;
              }}
            >
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
                    const timelineStop = timelineStopsById.get(stop.id);
                    const stopTime = timelineStop
                      ? timelineStopTimeLabel(timelineStop)
                      : null;
                    return (
                      <section className="story-photo-stop-grid" key={stop.id}>
                        <div className="story-photo-stop-heading">
                          <div>
                            <strong>{displayStopTitle(stop)}</strong>
                            {stopTime ? (
                              <time
                                className="story-photo-stop-time"
                                dateTime={stopTime.dateTime}
                              >
                                {stopTime.labels.join(" – ")}
                              </time>
                            ) : null}
                          </div>
                          <span aria-label={`${photos.length} photos`}>
                            <TimelineMetricIcon name="camera" />
                            {photos.length}
                          </span>
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
    capturedAtLocal: item.capturedAtLocal,
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
    capturedAtLocal: item.capturedAtLocal ?? null,
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
    capturedAtLocal: item.capturedAtLocal ?? null,
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
  const touchStartRef = useRef<{ x: number; y: number } | null>(null);
  const swipeTrackRef = useRef<HTMLDivElement>(null);
  const completedSwipeRef = useRef<number | null>(null);

  const photoAtOffset = useCallback(
    (delta: number) => {
      if (!selectedPhoto || photos.length === 0) {
        return null;
      }
      const index = (selectedIndex + delta + photos.length) % photos.length;
      return photos[index];
    },
    [photos, selectedIndex, selectedPhoto],
  );

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

  function rememberTouchStart(event: TouchEvent<HTMLDivElement>) {
    const touch = event.changedTouches[0];
    if (!touch) {
      return;
    }
    touchStartRef.current = { x: touch.clientX, y: touch.clientY };
    completedSwipeRef.current = null;
    updateSwipeOffset(0, false);
  }

  function forgetTouch() {
    touchStartRef.current = null;
    completedSwipeRef.current = null;
    updateSwipeOffset(0, true);
  }

  function updateSwipeOffset(offset: number, isSettling: boolean) {
    const track = swipeTrackRef.current;
    if (!track) {
      return;
    }
    track.style.setProperty("--photo-browser-swipe-offset", `${offset}px`);
    track.classList.toggle("is-settling", isSettling);
  }

  function handleTouchMove(event: TouchEvent<HTMLDivElement>) {
    const start = touchStartRef.current;
    const touch = event.touches[0];
    if (!start || !touch || !hasMultiple) {
      return;
    }
    const deltaX = touch.clientX - start.x;
    const deltaY = touch.clientY - start.y;
    if (Math.abs(deltaX) < 6 || Math.abs(deltaX) < Math.abs(deltaY) * 1.25) {
      return;
    }
    const stageWidth = event.currentTarget.clientWidth;
    const boundedOffset = Math.max(-stageWidth, Math.min(stageWidth, deltaX));
    updateSwipeOffset(boundedOffset, false);
  }

  function handleTouchEnd(event: TouchEvent<HTMLDivElement>) {
    const start = touchStartRef.current;
    const touch = event.changedTouches[0];
    touchStartRef.current = null;
    if (!start || !touch || !hasMultiple) {
      return;
    }
    const deltaX = touch.clientX - start.x;
    const deltaY = touch.clientY - start.y;
    const horizontalDistance = Math.abs(deltaX);
    const verticalDistance = Math.abs(deltaY);
    const stageWidth = event.currentTarget.clientWidth;
    if (
      horizontalDistance < 48 ||
      horizontalDistance < verticalDistance * 1.25
    ) {
      completedSwipeRef.current = null;
      updateSwipeOffset(0, true);
      return;
    }
    const delta = deltaX > 0 ? -1 : 1;
    completedSwipeRef.current = delta;
    updateSwipeOffset(delta * -stageWidth, true);
  }

  function finishSwipe() {
    const completedDelta = completedSwipeRef.current;
    completedSwipeRef.current = null;
    if (completedDelta !== null) {
      flushSync(() => {
        onSelect(photoAtOffset(completedDelta)?.id ?? selectedPhoto!.id);
      });
      updateSwipeOffset(0, false);
      return;
    }
    updateSwipeOffset(0, false);
  }

  if (!selectedPhoto) {
    return null;
  }
  const previousPhoto = photoAtOffset(-1);
  const nextPhoto = photoAtOffset(1);

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
              {formatReconstructionTime(
                selectedPhoto.capturedAt,
                selectedPhoto.capturedAtLocal ?? null,
                timezoneId,
              )}
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
        <div
          className="photo-browser-stage"
          onTouchStart={rememberTouchStart}
          onTouchMove={handleTouchMove}
          onTouchCancel={forgetTouch}
          onTouchEnd={handleTouchEnd}
        >
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
            <div className="photo-browser-swipe-track" ref={swipeTrackRef}>
              {previousPhoto?.imageUrl ? (
                <img
                  className="photo-browser-image photo-browser-image-adjacent previous"
                  src={previousPhoto.imageUrl}
                  alt=""
                />
              ) : (
                <div className="photo-browser-missing photo-browser-image-adjacent previous">
                  Preview unavailable
                </div>
              )}
              <img
                className="photo-browser-image current"
                src={selectedPhoto.imageUrl}
                alt={selectedPhoto.filename ?? "Trip photo"}
                onTransitionEnd={finishSwipe}
              />
              {nextPhoto?.imageUrl ? (
                <img
                  className="photo-browser-image photo-browser-image-adjacent next"
                  src={nextPhoto.imageUrl}
                  alt=""
                />
              ) : (
                <div className="photo-browser-missing photo-browser-image-adjacent next">
                  Preview unavailable
                </div>
              )}
            </div>
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

function TimelineChevron({
  direction,
}: {
  direction: "down" | "right" | "up";
}) {
  const pathByDirection = {
    down: "m6 9 6 6 6-6",
    right: "m9 6 6 6-6 6",
    up: "m6 15 6-6 6 6",
  } as const;

  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d={pathByDirection[direction]} />
    </svg>
  );
}

function TimelineMoreIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <circle cx="5" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="19" cy="12" r="1.5" fill="currentColor" stroke="none" />
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
  const mapRouteCollection = useMemo(
    () =>
      state.viewMode === "DAY"
        ? { type: "FeatureCollection" as const, features: [] }
        : routeCollection,
    [routeCollection, state.viewMode],
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
    routeCollection: mapRouteCollection,
    stopCollection,
  });

  useEffect(() => {
    mapDataRef.current = {
      areaCollection,
      mediaCollection,
      routeCollection: mapRouteCollection,
      stopCollection,
    };
  }, [areaCollection, mapRouteCollection, mediaCollection, stopCollection]);
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
      mapRouteCollection,
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
  }, [areaCollection, mapRouteCollection, mediaCollection, stopCollection]);

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
        element.className =
          state.viewMode === "DAY" && state.selectedDayId === dayId
            ? "photo-day-marker day-focused"
            : "photo-day-marker";
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
    state.viewMode,
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
      {activeDayLabel ? (
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

type ExampleTripStop = {
  id: string;
  day: string;
  title: string;
  description: string;
  coordinates: [number, number];
  image: string;
  imageAlt: string;
};

const exampleTripStops: ExampleTripStop[] = [
  {
    id: "seongsan",
    day: "Day 1",
    title: "Seongsan",
    description: "Sunrise, coastal walks, and 24 shared photos",
    coordinates: [126.9327, 33.4581],
    image: "/example-trip/jeju-sunrise.png",
    imageAlt: "Sunrise over the coast of Jeju Island",
  },
  {
    id: "seopjikoji",
    day: "Day 1",
    title: "Seopjikoji coast",
    description: "A bright afternoon along Jeju's volcanic shore",
    coordinates: [126.9289, 33.4236],
    image: "/example-trip/jeju-coast.png",
    imageAlt: "Volcanic coast and turquoise water on Jeju Island",
  },
  {
    id: "hallasan",
    day: "Day 2",
    title: "Hallasan",
    description: "A trail day captured from four perspectives",
    coordinates: [126.5327, 33.3617],
    image: "/example-trip/hallasan-hike.png",
    imageAlt: "Travelers hiking a green trail on Hallasan",
  },
  {
    id: "dongmun",
    day: "Day 2",
    title: "Dongmun Market",
    description: "Market finds and the last dinner together",
    coordinates: [126.5261, 33.5121],
    image: "/example-trip/jeju-market.png",
    imageAlt: "Friends visiting a warm-lit Jeju market",
  },
];

const sampleTripUrl =
  "https://tripweave.chronotrailai.com/story/korea-aef41b9bcda5/v/2";

function ExampleTripPreview({ onBack }: { onBack: () => void }) {
  return (
    <section className="example-trip" aria-labelledby="example-trip-title">
      <header className="example-trip-header">
        <div>
          <p className="eyebrow">Read-only example</p>
          <h1 id="example-trip-title">Explore a real shared trip</h1>
          <p>See how photos become a map, timeline, and story.</p>
        </div>
        <button className="secondary-button" type="button" onClick={onBack}>
          Back to start
        </button>
      </header>

      <section
        className="example-trip-guide"
        aria-label="How to explore this trip"
      >
        <div>
          <span className="example-trip-guide-icon" aria-hidden="true">
            <StoryHeaderIcon action="map" />
          </span>
          <p>
            <strong>Explore the map</strong>
            <span>
              Tap a day photo marker to jump into its stops, or select a stop to
              follow the route.
            </span>
          </p>
        </div>
        <div>
          <span className="example-trip-guide-icon" aria-hidden="true">
            <StoryHeaderIcon action="timeline" />
          </span>
          <p>
            <strong>Follow the timeline</strong>
            <span>See the trip unfold moment by moment.</span>
          </p>
        </div>
        <div>
          <span className="example-trip-guide-icon" aria-hidden="true">
            <StoryHeaderIcon action="slideshow" />
          </span>
          <p>
            <strong>Play the story</strong>
            <span>Sit back and relive the journey.</span>
          </p>
        </div>
      </section>

      <div className="example-trip-frame">
        <iframe
          title="Sample TripWeave story"
          src={sampleTripUrl}
          allow="fullscreen"
        />
      </div>

      <footer className="example-trip-footer">
        <div>
          <strong>This is a real TripWeave story.</strong>
          <p>Explore it freely, then create a trip of your own.</p>
        </div>
        <a
          className="secondary-button"
          href={sampleTripUrl}
          target="_blank"
          rel="noreferrer"
        >
          Open in a new tab
        </a>
      </footer>
    </section>
  );
}

function LegacyExampleTripPreview({ onBack }: { onBack: () => void }) {
  const [selectedStopId, setSelectedStopId] = useState(exampleTripStops[0].id);

  return (
    <section className="example-trip" aria-labelledby="example-trip-title">
      <header className="example-trip-header">
        <div>
          <p className="eyebrow">Read-only example</p>
          <h1 id="example-trip-title">A Weekend in Jeju</h1>
          <p>May 16–18 · 4 travelers · 86 photos</p>
        </div>
        <button className="secondary-button" type="button" onClick={onBack}>
          Back to start
        </button>
      </header>

      <div className="example-trip-grid">
        <section
          className="example-story-card"
          aria-labelledby="example-story-title"
        >
          <div className="example-photo-grid" aria-label="Example trip photos">
            {exampleTripStops.map((stop) => (
              <button
                className={
                  stop.id === selectedStopId
                    ? "example-photo active"
                    : "example-photo"
                }
                key={stop.id}
                type="button"
                onClick={() => setSelectedStopId(stop.id)}
              >
                <NextImage
                  alt={stop.imageAlt}
                  fill
                  sizes="(max-width: 760px) 50vw, 24vw"
                  src={stop.image}
                />
              </button>
            ))}
          </div>
          <section
            className="example-map-card"
            aria-labelledby="example-map-title"
          >
            <div className="example-map-heading">
              <div>
                <p className="eyebrow">The route</p>
                <h2 id="example-map-title">Four stops, one shared map.</h2>
              </div>
              <span>2 days</span>
            </div>
            <ExampleTripMap
              activeStopId={selectedStopId}
              onSelectStop={setSelectedStopId}
            />
          </section>
          <div className="example-story-copy">
            <p className="eyebrow">The story</p>
            <h2 id="example-story-title">One trip, seen through every lens.</h2>
            <p>
              Photos from everyone&apos;s camera rolls come together as one
              journey — from the first sunrise to the last shared dinner.
            </p>
          </div>
        </section>

        <aside
          className="example-timeline"
          aria-labelledby="example-timeline-title"
        >
          <div>
            <p className="eyebrow">Timeline</p>
            <h2 id="example-timeline-title">Follow the journey</h2>
          </div>
          <ol>
            {exampleTripStops.map((stop) => (
              <li key={stop.id}>
                <button
                  className={
                    stop.id === selectedStopId
                      ? "example-stop-marker active"
                      : "example-stop-marker"
                  }
                  type="button"
                  onClick={() => setSelectedStopId(stop.id)}
                  aria-label={`Show ${stop.title} on the map`}
                />
                <button
                  className={
                    stop.id === selectedStopId
                      ? "example-timeline-stop active"
                      : "example-timeline-stop"
                  }
                  type="button"
                  onClick={() => setSelectedStopId(stop.id)}
                >
                  <strong>
                    {stop.day} · {stop.title}
                  </strong>
                  <span>{stop.description}</span>
                </button>
              </li>
            ))}
          </ol>
        </aside>
      </div>

      <footer className="example-trip-footer">
        <div>
          <strong>This is what your trip can become.</strong>
          <p>
            Create a trip, add everyone&apos;s photos, and let the story take
            shape.
          </p>
        </div>
        <button type="button" onClick={onBack}>
          Create your own trip
        </button>
      </footer>
    </section>
  );
}

function ExampleTripMap({
  activeStopId,
  onSelectStop,
}: {
  activeStopId: string;
  onSelectStop: (stopId: string) => void;
}) {
  const mapNode = useRef<HTMLDivElement | null>(null);
  const markerNodes = useRef(new Map<string, HTMLButtonElement>());

  useEffect(() => {
    if (!mapNode.current) {
      return;
    }
    const markers = markerNodes.current;
    const map = new maplibregl.Map({
      container: mapNode.current,
      style: configuredMapStyle(),
      center: [126.72, 33.43],
      zoom: 9.3,
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
    });
    const route = {
      type: "Feature" as const,
      properties: {},
      geometry: {
        type: "LineString" as const,
        coordinates: exampleTripStops.map((stop) => stop.coordinates),
      },
    };
    map.on("load", () => {
      map.addSource("example-trip-route", { type: "geojson", data: route });
      map.addLayer({
        id: "example-trip-route-line",
        type: "line",
        source: "example-trip-route",
        paint: {
          "line-color": "#23695b",
          "line-width": 3,
          "line-opacity": 0.88,
        },
      });
      for (const stop of exampleTripStops) {
        const markerNode = document.createElement("button");
        markerNode.type = "button";
        markerNode.className = "example-map-marker";
        markerNode.setAttribute("aria-label", `Show ${stop.title}`);
        markerNode.innerHTML = `<img src="${stop.image}" alt="" />`;
        markerNode.addEventListener("click", () => onSelectStop(stop.id));
        markers.set(stop.id, markerNode);
        new maplibregl.Marker({ element: markerNode, anchor: "bottom" })
          .setLngLat(stop.coordinates)
          .addTo(map);
      }
    });
    return () => {
      markers.clear();
      map.remove();
    };
  }, [onSelectStop]);

  useEffect(() => {
    markerNodes.current.forEach((marker, stopId) => {
      marker.classList.toggle("active", stopId === activeStopId);
    });
  }, [activeStopId]);

  return <div ref={mapNode} className="example-trip-map" />;
}

function TripFields({
  form,
  onChange,
  showDayCutoffHour = true,
}: {
  form: TripForm;
  onChange: (form: TripForm) => void;
  showDayCutoffHour?: boolean;
}) {
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
      {showDayCutoffHour ? (
        <label>
          New day starts at
          <input
            max={23}
            min={0}
            type="number"
            value={form.dayCutoffHour}
            onChange={(event) => setField("dayCutoffHour", event.target.value)}
            required
          />
          <small>
            Photos before this hour are grouped with the previous day.
          </small>
        </label>
      ) : null}
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
            <strong>First story is being prepared</strong>
            <small>
              {canUpdateStory
                ? "It will appear automatically when photo processing finishes."
                : "An organizer can review it once photo processing finishes."}
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
  onCopyUrl,
}: {
  invitations: InvitationResponse[];
  onRevoke: (invitation: InvitationResponse) => void;
  onCopyUrl: (url: string) => void;
}) {
  if (invitations.length === 0) {
    return <p>No invitations yet.</p>;
  }
  return (
    <div className="simple-list" role="list">
      {invitations.map((invitation) => (
        <InvitationCard
          invitation={invitation}
          key={invitation.id}
          onCopyUrl={onCopyUrl}
          onRevoke={onRevoke}
        />
      ))}
    </div>
  );
}

function InvitationCard({
  invitation,
  onRevoke,
  onCopyUrl,
}: {
  invitation: InvitationResponse;
  onRevoke: (invitation: InvitationResponse) => void;
  onCopyUrl: (url: string) => void;
}) {
  const [qrUrl, setQrUrl] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (!invitation.inviteUrl) {
      return;
    }
    QRCode.toDataURL(invitation.inviteUrl, {
      errorCorrectionLevel: "M",
      margin: 1,
      width: 160,
    })
      .then((url) => {
        if (!cancelled) setQrUrl(url);
      })
      .catch(() => {
        if (!cancelled) setQrUrl("");
      });
    return () => {
      cancelled = true;
    };
  }, [invitation.inviteUrl]);

  return (
    <article className="invite-card" role="listitem">
      <div className="invite-card-header">
        <div>
          <strong>{invitation.role}</strong>
          <small>
            {invitation.status} · {invitation.useCount}/{invitation.maxUses}{" "}
            joined
          </small>
        </div>
        {invitation.status !== "revoked" ? (
          <button type="button" onClick={() => onRevoke(invitation)}>
            Revoke
          </button>
        ) : null}
      </div>
      {invitation.inviteUrl ? (
        <div className="invite-card-content">
          <div>
            <code>{invitation.inviteUrl}</code>
            <button
              type="button"
              onClick={() => onCopyUrl(invitation.inviteUrl!)}
            >
              Copy link
            </button>
          </div>
          {qrUrl ? (
            <img className="qr-block" src={qrUrl} alt="Invitation QR code" />
          ) : null}
        </div>
      ) : null}
    </article>
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
  onCopyUrl,
}: {
  publications: PublicationsListResponse | null;
  onRevoke: (id: string) => void;
  onCopyUrl: (url: string) => void;
}) {
  if (!publications) {
    return <p>No publication data loaded.</p>;
  }
  const versionsById = new Map(
    publications.versions.map((version) => [version.id, version]),
  );
  return (
    <div className="publication-list">
      <h3>Published versions</h3>
      {publications.shareLinks.length === 0 ? (
        <p>No versions yet.</p>
      ) : (
        <div className="compact-list">
          {publications.shareLinks.map((link) => {
            const version = link.storyVersionId
              ? versionsById.get(link.storyVersionId)
              : undefined;
            return (
              <article className="publication-card" key={link.id}>
                <div className="publication-card-status">
                  <strong>
                    {version
                      ? `Version ${version.versionNumber}`
                      : "Publishing"}
                  </strong>
                  <span>{version?.state ?? link.status}</span>
                  {link.status === "active" ? (
                    <button type="button" onClick={() => onRevoke(link.id)}>
                      Revoke
                    </button>
                  ) : null}
                </div>
                {link.versionStoryUrl ? (
                  <div className="publication-card-link">
                    <code>{link.versionStoryUrl}</code>
                    <button
                      type="button"
                      onClick={() => onCopyUrl(link.versionStoryUrl!)}
                    >
                      Copy version link
                    </button>
                  </div>
                ) : null}
                {version?.errorMessage ? (
                  <small className="error">{version.errorMessage}</small>
                ) : null}
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}

function PublicStoryViewer({
  slug,
  versionNumber,
  initialView = "story",
}: {
  slug: string;
  versionNumber?: number;
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
      .publicStory(slug, versionNumber)
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
  }, [slug, versionNumber]);

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
        onOpenPhotos={() => setMobilePane("photos")}
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
    { type: "trip" | "day" | "stop" }
  > | null>(() => {
    const firstMapScene = scenes.find((scene) => scene.type !== "photo");
    return firstMapScene ?? null;
  });
  const hasMultipleScenes = scenes.length > 1;
  const activeMapScene =
    activeScene?.type === "trip" ||
    activeScene?.type === "day" ||
    activeScene?.type === "stop"
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
        {activeScene?.type === "trip" ? (
          <span className="slideshow-trip-overview-title">{title}</span>
        ) : null}
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
      {activeScene?.type === "trip" ||
      activeScene?.type === "day" ||
      activeScene?.type === "stop" ? (
        <footer
          className={`slideshow-caption map-caption ${
            activeScene.type === "trip"
              ? "slideshow-trip-overview-caption"
              : activeScene.type === "day"
                ? "slideshow-day-overview-caption"
                : "slideshow-stop-caption"
          }`}
        >
          <div className="slideshow-caption-copy">
            <span className="slideshow-trip-title">{title}</span>
            <span className="slideshow-caption-kicker">
              {activeScene.type === "trip"
                ? "Trip overview"
                : activeScene.type === "day"
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
              <span>
                {formatReconstructionTime(
                  activePhoto.capturedAt,
                  activePhoto.capturedAtLocal,
                  timezoneId,
                )}
              </span>
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
          className={`slideshow-photo-layer slideshow-photo-layer-previous ${slideshowPhotoMotion(
            previousPhoto.id,
          )}`}
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
          >
            <div
              aria-hidden="true"
              className={`slideshow-photo-motion ${
                reducedMotion ? "" : slideshowPhotoMotion(displayedPhoto.id)
              }`}
              style={{ backgroundImage: `url("${displayedPhoto.imageUrl}")` }}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function slideshowPhotoMotion(photoId: string): string {
  let hash = 0;
  for (const character of photoId) {
    hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  }
  return [
    "slideshow-photo-motion-zoom-in",
    "slideshow-photo-motion-pan-right",
    "slideshow-photo-motion-pan-left",
    "slideshow-photo-motion-pan-up",
  ][hash % 4];
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
  scene: Extract<SlideshowScene, { type: "trip" | "day" | "stop" }>;
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

    const stopsByMarkerDepth =
      scene.type === "stop"
        ? [
            ...scene.stops.filter((stop) => stop.id !== scene.activeStopId),
            ...scene.stops.filter((stop) => stop.id === scene.activeStopId),
          ]
        : scene.stops;
    const activeStop =
      scene.type === "stop"
        ? scene.stops.find((stop) => stop.id === scene.activeStopId)
        : null;

    // MapLibre stacks DOM markers in insertion order, so add the current stop last.
    if (scene.type === "trip") {
      for (const dayMarker of scene.dayMarkers) {
        const element = document.createElement("div");
        element.className = "slideshow-day-map-marker";
        const image = document.createElement("img");
        image.src = dayMarker.imageUrl;
        image.alt = "";
        const label = document.createElement("span");
        label.textContent = dayMarker.label;
        element.append(image, label);
        markersRef.current.push(
          new maplibregl.Marker({ element, anchor: "center" })
            .setLngLat(dayMarker.coordinates)
            .addTo(map),
        );
      }
    }
    for (const stop of stopsByMarkerDepth) {
      if (scene.type === "trip") {
        continue;
      }
      if (!stop.coordinates) {
        continue;
      }
      const element = document.createElement("div");
      element.className =
        scene.type === "stop" && stop.id === scene.activeStopId
          ? "slideshow-map-marker active"
          : "slideshow-map-marker";
      element.textContent = String(stop.position);
      if (scene.type === "stop" && stop.id === activeStop?.id) {
        const label = document.createElement("span");
        label.className = "slideshow-map-marker-label";
        label.textContent = stop.label;
        element.append(label);
      }
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

function TimelineMetricIcon({ name }: { name: TimelineMetricIconName }) {
  if (name === "stops") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M12 21s6-5.1 6-11a6 6 0 1 0-12 0c0 5.9 6 11 6 11Z" />
        <path d="M12 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z" />
      </svg>
    );
  }

  if (name === "camera") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M4 8.5h3l1.5-2h7l1.5 2h3v9.5H4z" />
        <path d="M12 11a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z" />
        <path d="M18 11h.01" />
      </svg>
    );
  }

  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z" />
      <path d="M17 10a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z" />
      <path d="M3.5 19a5.5 5.5 0 0 1 11 0" />
      <path d="M14 18.5a4.2 4.2 0 0 1 6.5.5" />
    </svg>
  );
}

function StoryHeaderIcon({ action }: { action: StoryHeaderIconAction }) {
  if (action === "trips") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <rect x="4" y="4" width="16" height="5" rx="1" />
        <rect x="4" y="11" width="16" height="5" rx="1" />
        <path d="M7 6.5h.01M7 13.5h.01M10 6.5h6M10 13.5h6" />
      </svg>
    );
  }

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

  if (action === "help") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="8.5" />
        <path d="M9.7 9.4a2.5 2.5 0 1 1 4.3 1.7c-.9.9-2 1.4-2 2.8" />
        <path d="M12 17h.01" />
      </svg>
    );
  }

  if (action === "browse") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M9 18 3 21V6l6-3 6 3 6-3v15l-6 3-6-3Z" />
        <path d="M9 3v15" />
        <path d="M15 6v15" />
        <path d="M12 9.5a2.2 2.2 0 1 0 0 4.4 2.2 2.2 0 0 0 0-4.4Z" />
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

function MediaActionIcon({
  action,
}: {
  action: "members" | "public" | "help" | "delete" | "location";
}) {
  if (action === "members") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <circle cx="9" cy="8" r="3" />
        <path d="M3.5 19a5.5 5.5 0 0 1 11 0" />
        <path d="M16 5.5a2.5 2.5 0 0 1 0 5M17.5 14a4.5 4.5 0 0 1 3 4.2" />
      </svg>
    );
  }

  if (action === "public") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="8.5" />
        <path d="M3.5 12h17M12 3.5a13.5 13.5 0 0 1 0 17M12 3.5a13.5 13.5 0 0 0 0 17" />
      </svg>
    );
  }

  if (action === "help") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="8.5" />
        <path d="M9.8 9a2.4 2.4 0 1 1 3.8 1.9c-1 .7-1.6 1.2-1.6 2.6" />
        <path d="M12 16.8h.01" />
      </svg>
    );
  }

  if (action === "delete") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5" />
      </svg>
    );
  }

  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M12 21s6-5.2 6-11a6 6 0 1 0-12 0c0 5.8 6 11 6 11Z" />
      <circle cx="12" cy="10" r="2" />
    </svg>
  );
}

function MediaList({
  media,
  onRetry,
  onVisibilityChange,
  canChangeVisibility,
  onDelete,
  onAdjustLocation,
  timezoneId,
}: {
  media: MediaItemResponse[];
  onRetry?: (item: MediaItemResponse) => void;
  onVisibilityChange?: (item: MediaItemResponse, visibility: string) => void;
  canChangeVisibility?: (item: MediaItemResponse) => boolean;
  onDelete?: (item: MediaItemResponse) => void;
  onAdjustLocation?: (item: MediaItemResponse) => void;
  timezoneId?: string;
}) {
  const [selectedPhotoId, setSelectedPhotoId] = useState<string | null>(null);
  const [visibilityHelpItemId, setVisibilityHelpItemId] = useState<
    string | null
  >(null);
  const galleryPhotos = useMemo(
    () => media.map(galleryPhotoFromMediaItem),
    [media],
  );
  if (media.length === 0) {
    return <p>No processed media yet.</p>;
  }
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
              {onVisibilityChange &&
              (canChangeVisibility ? canChangeVisibility(item) : true) ? (
                <div className="media-property-row media-visibility-row">
                  <span>Visibility</span>
                  <div className="visibility-control">
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
                    <div className="visibility-help">
                      <button
                        className="media-icon-button"
                        type="button"
                        aria-label="Photo visibility help"
                        aria-expanded={visibilityHelpItemId === item.id}
                        aria-controls={`visibility-help-${item.id}`}
                        onClick={() =>
                          setVisibilityHelpItemId((current) =>
                            current === item.id ? null : item.id,
                          )
                        }
                        title="Photo visibility help"
                      >
                        <MediaActionIcon action="help" />
                      </button>
                      {visibilityHelpItemId === item.id ? (
                        <div
                          className="visibility-help-popover"
                          id={`visibility-help-${item.id}`}
                          role="dialog"
                          aria-label="Photo visibility help"
                        >
                          <div>
                            <strong>Who can see this photo?</strong>
                            <p>
                              Member only keeps it inside this trip. Public lets
                              it appear in a published story.
                            </p>
                            <p>
                              Published stories use a sanitized derivative,
                              never the original photo.
                            </p>
                          </div>
                          <button
                            className="visibility-help-close"
                            type="button"
                            onClick={() => setVisibilityHelpItemId(null)}
                            aria-label="Close photo visibility help"
                          >
                            ×
                          </button>
                        </div>
                      ) : null}
                    </div>
                  </div>
                </div>
              ) : null}
              <dl>
                <div>
                  <dt>Captured</dt>
                  <dd>
                    {formatReconstructionTime(
                      item.capturedAt ?? null,
                      item.capturedAtLocal ?? null,
                      timezoneId,
                    )}
                  </dd>
                </div>
                <div className="media-gps-row">
                  <dt>GPS</dt>
                  <dd>
                    <span>{item.gpsPresent ? "Present" : "Not found"}</span>
                    {onAdjustLocation ? (
                      <button
                        className="media-inline-action"
                        type="button"
                        onClick={() => onAdjustLocation(item)}
                      >
                        Update
                      </button>
                    ) : null}
                  </dd>
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
              {onDelete ? (
                <button
                  className="danger media-delete-button"
                  type="button"
                  onClick={() => onDelete(item)}
                >
                  Delete photo
                </button>
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

function MediaLocationDialog({
  media,
  onCancel,
  onSave,
}: {
  media: MediaItemResponse;
  onCancel: () => void;
  onSave: (latitude: number, longitude: number) => Promise<void>;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const savedLocation: [number, number] | null =
    media.latitude != null && media.longitude != null
      ? [media.longitude, media.latitude]
      : null;
  const hasSavedLocation = savedLocation !== null;
  const [center, setCenter] = useState<[number, number]>([
    media.longitude ?? 127,
    media.latitude ?? 35,
  ]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!containerRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: configuredMapStyle(),
      center,
      zoom: media.latitude == null || media.longitude == null ? 4 : 14,
    });
    const currentLocationMarker = savedLocation
      ? new maplibregl.Marker({
          anchor: "center",
          element: Object.assign(document.createElement("div"), {
            className: "media-location-current-marker",
          }),
        })
          .setLngLat(savedLocation)
          .addTo(map)
      : null;
    map.on("move", () => {
      const next = map.getCenter();
      setCenter([next.lng, next.lat]);
    });
    mapRef.current = map;
    return () => {
      currentLocationMarker?.remove();
      map.remove();
    };
  }, []); // The dialog is recreated for each photo.

  async function submit() {
    setSaving(true);
    setError("");
    try {
      await onSave(center[1], center[0]);
    } catch (reason) {
      setError(messageFrom(reason));
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section
        className="media-location-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Adjust photo location"
      >
        <header className="media-location-dialog-header">
          <div>
            <p className="eyebrow">Photo location</p>
            <h2>{media.filename ?? "Photo"}</h2>
            <p>Move the map until the desired place is under the center pin.</p>
          </div>
          <button
            type="button"
            className="secondary-button"
            onClick={onCancel}
            disabled={saving}
          >
            Cancel
          </button>
        </header>
        <div className="media-location-map" ref={containerRef}>
          <span className="media-location-pin" aria-hidden="true">
            ●
          </span>
        </div>
        <footer className="media-location-dialog-footer">
          <div className="media-location-status">
            <small>Selected location</small>
            <strong>
              {center[1].toFixed(6)}, {center[0].toFixed(6)}
            </strong>
            {hasSavedLocation ? (
              <small className="media-location-current-label">
                <span aria-hidden="true" />
                Blue dot: current photo location
              </small>
            ) : (
              <small>No location saved for this photo yet.</small>
            )}
          </div>
          {error ? <p className="error">{error}</p> : null}
          <div className="button-row">
            <button
              type="button"
              onClick={() => void submit()}
              disabled={saving}
            >
              {saving ? "Saving…" : "Use this location"}
            </button>
          </div>
        </footer>
      </section>
    </div>
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
    weekday: new Intl.DateTimeFormat(undefined, { weekday: "short" }).format(
      date,
    ),
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
  _timezoneId?: string,
): string {
  if (localValue) {
    return formatFloatingDate(localValue);
  }
  // A time without a GPS-derived local representation is deliberately shown
  // in UTC. A trip-wide timezone would be wrong for a multi-country trip.
  return formatDate(utcValue, "UTC");
}

function formatTimelineStopTime(
  utcValue: string | null,
  localValue: string | null,
  _timezoneId?: string,
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
      timeZone: "UTC",
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
