"use client";

import {
  ChangeEvent,
  DragEvent,
  FormEvent,
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
import { ApiError, api, uploadWithProgress } from "./api-client";
import type {
  GuestMemberResponse,
  InvitationPreviewResponse,
  InvitationResponse,
  MediaItemResponse,
  MemberResponse,
  PublicationsListResponse,
  PublicStoryResponse,
  ReconstructionResponse,
  SimilarityGroupResponse,
  TripResponse,
  UploadFileResponse,
  UploadSessionResponse,
  UserResponse,
} from "./api-types";
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
  filename: string | null;
  contributor: string;
  capturedAt: string | null;
  contextLabel?: string | null;
};

type AuthMode = "login" | "register";
type LoadState = "loading" | "ready";
type MobileWorkspaceTab = "story" | "timeline" | "photos" | "share" | "more";
type StoryMobilePane = "map" | "timeline" | "photos";

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
    return (
      <PublicStoryViewer
        token={decodeURIComponent(path.slice("/story/".length))}
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
  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [authError, setAuthError] = useState("");
  const [tripError, setTripError] = useState("");
  const [createForm, setCreateForm] = useState<TripForm>(emptyTripForm);
  const [settingsForm, setSettingsForm] = useState<TripForm>(emptyTripForm);
  const [isBusy, setIsBusy] = useState(false);
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
  const storyUpdate = reconstruction?.storyUpdate ?? null;
  const storyUpdateNeeded = Boolean(storyUpdate?.needsUpdate);
  const storyUpdateLabel = storyUpdate
    ? storyUpdate.unassignedReadyMediaCount > 0
      ? `${storyUpdate.unassignedReadyMediaCount} new photo${
          storyUpdate.unassignedReadyMediaCount === 1 ? "" : "s"
        } need update`
      : "Story is up to date"
    : "";

  const selectedUploadFiles = useMemo(
    () => uploadSessions.flatMap((session) => session.files),
    [uploadSessions],
  );

  const overallProgress = useMemo(() => {
    const entries = Object.values(uploadProgress);
    const loaded = entries.reduce((total, item) => total + item.loaded, 0);
    const total = entries.reduce((sum, item) => sum + item.total, 0);
    return total > 0 ? Math.round((loaded / total) * 100) : 0;
  }, [uploadProgress]);

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
      setSelectedTripId(next);
      setSettingsForm(nextTrip ? fromTrip(nextTrip) : emptyTripForm);
      setStoryState(initialStoryMapState());
    },
    [],
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
      return;
    }
    const result = await api.reconstruction(tripId);
    setReconstruction(result);
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
    setSelectedTripId(trip.id);
    setSettingsForm(fromTrip(trip));
    void loadUploadSessions(trip.id);
    void loadMedia(trip.id);
    void loadReconstruction(trip.id);
    void loadCollaboration(trip.id);
    void loadPublications(trip.id);
  }

  function removeTripFromState(tripId: string) {
    const remaining = trips.filter((trip) => trip.id !== tripId);
    const nextTrip = remaining[0] ?? null;
    setTrips(remaining);
    setSelectedTripId(nextTrip?.id ?? null);
    setSettingsForm(nextTrip ? fromTrip(nextTrip) : emptyTripForm);
    if (!nextTrip) {
      setUploadSessions([]);
      setMedia([]);
      setSimilarityGroups([]);
      setReconstruction(null);
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
        await loadTrips();
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
        loadReconstruction(selectedTrip.id).catch((error) =>
          setReconstructionError(messageFrom(error)),
        ),
      );
    }
  }, [loadReconstruction, selectedTrip?.id]);

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
          await loadReconstruction(tripId);
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
  }, [hasProcessingMedia, loadReconstruction, selectedTrip?.id]);

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
      setSelectedTripId(null);
      setUploadSessions([]);
      setMedia([]);
      setSimilarityGroups([]);
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
          mimeType: file.type || "application/octet-stream",
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
      await loadReconstruction(selectedTrip.id);
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
        await loadReconstruction(selectedTrip.id);
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
      await loadReconstruction(selectedTrip.id);
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
    if (!selectedTrip) {
      return;
    }
    setReconstructionError("");
    setIsBusy(true);
    try {
      const result = await api.startReconstruction(selectedTrip.id);
      setReconstruction(result);
      await loadMedia(selectedTrip.id);
    } catch (error) {
      setReconstructionError(messageFrom(error));
    } finally {
      setIsBusy(false);
    }
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
    setReconstructionError("");
    try {
      await api.createEditOperation(selectedTrip.id, {
        operationType: "rename_stop",
        payload: { stopId, title },
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

  async function splitStop(stopId: string, afterMomentId: string) {
    if (!selectedTrip) {
      return;
    }
    setReconstructionError("");
    try {
      await api.createEditOperation(selectedTrip.id, {
        operationType: "split_stop",
        payload: { stopId, afterMomentId },
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
    <main className="app-shell">
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

      <nav className="mobile-workspace-tabs" aria-label="Trip sections">
        {(
          [
            ["story", "Story"],
            ["timeline", "Timeline"],
            ["photos", "Photos"],
            ["share", "Share"],
            ["more", "More"],
          ] as Array<[MobileWorkspaceTab, string]>
        ).map(([tab, label]) => (
          <button
            type="button"
            aria-pressed={mobileTab === tab}
            className={mobileTab === tab ? "active" : ""}
            key={tab}
            onClick={() => setMobileTab(tab)}
          >
            {label}
          </button>
        ))}
      </nav>

      <section className="workspace trip-workspace">
        <aside
          className={`trip-nav panel ${
            mobileTab === "more" ? "mobile-tab-active" : ""
          }`}
          aria-label="Trip navigation"
          data-mobile-tab-panel="more"
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
                disabled={isBusy}
              >
                Update story
              </button>
              {storyUpdate ? (
                <span
                  className={
                    storyUpdateNeeded
                      ? "story-update-status needs-update"
                      : "story-update-status"
                  }
                >
                  {storyUpdateLabel}
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
                {["owner", "editor"].includes(selectedTrip.role) ? (
                  <div className="button-row">
                    <div className="story-action-stack">
                      <button
                        className={
                          storyUpdateNeeded ? "needs-update" : undefined
                        }
                        type="button"
                        onClick={runReconstruction}
                        disabled={isBusy}
                      >
                        Update story
                      </button>
                      {storyUpdate ? (
                        <span
                          className={
                            storyUpdateNeeded
                              ? "story-update-status needs-update"
                              : "story-update-status"
                          }
                        >
                          {storyUpdateLabel}
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
              {reconstructionError ? (
                <p className="error">{reconstructionError}</p>
              ) : null}
              {selectedTrip &&
              ["owner", "editor"].includes(selectedTrip.role) ? (
                <TripStoryExplorer
                  reconstruction={reconstruction}
                  state={storyState}
                  onStateChange={setStoryState}
                  onMergeStops={mergeStops}
                  onRenameStop={renameStop}
                  onSplitStop={splitStop}
                  mobilePane={mobileTab === "timeline" ? "timeline" : "map"}
                  timezoneId={selectedTrip.timezoneId}
                />
              ) : (
                <div className="story-empty">
                  <p>This trip is not editable from this workspace.</p>
                </div>
              )}
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
                {overallProgress > 0 ? (
                  <div>
                    <label htmlFor="overall-upload-progress">
                      Overall progress
                    </label>
                    <progress
                      id="overall-upload-progress"
                      max={100}
                      value={overallProgress}
                    />
                  </div>
                ) : null}
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
                  onRetry={retryMedia}
                  onVisibilityChange={updateMediaVisibility}
                  timezoneId={selectedTrip?.timezoneId}
                />
                <SimilarityGroupsPanel
                  groups={similarityGroups}
                  onChangeRepresentative={(groupId, mediaId) =>
                    void changeSimilarityRepresentative(groupId, mediaId)
                  }
                />
              </div>
            ) : (
              <p>Select a trip before uploading photos.</p>
            )}
          </details>

          {selectedTrip?.role === "owner" ? (
            <details
              className={`management-panel ${
                mobileTab === "more" ? "mobile-tab-active" : ""
              }`}
              id="travelers-panel"
              open={isMobileWorkspace ? mobileTab === "more" : undefined}
              data-mobile-tab-panel="more"
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
                mobileTab === "more" ? "mobile-tab-active" : ""
              }`}
              id="review-panel"
              open={isMobileWorkspace ? mobileTab === "more" : undefined}
              data-mobile-tab-panel="more"
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
              mobileTab === "more" ? "mobile-tab-active" : ""
            }`}
            id="settings-panel"
            open={isMobileWorkspace ? mobileTab === "more" : undefined}
            data-mobile-tab-panel="more"
          >
            <summary>
              <span>Settings</span>
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

  async function accept(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const guest = await api.acceptInvitation(token, { displayName });
      window.location.assign(`/contribute/${guest.tripId}`);
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
        {preview ? <p>Join this trip as a {preview.role}.</p> : null}
        <form className="stack" onSubmit={accept}>
          <label>
            Display name
            <input
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              required
              maxLength={160}
            />
          </label>
          {error ? <p className="error">{error}</p> : null}
          <button type="submit" disabled={busy || !preview}>
            Join trip
          </button>
        </form>
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
      api.uploadSessions(tripId),
      api.media(tripId),
    ]);
    setUploadSessions(sessionResult.uploadSessions);
    setMedia(mediaResult.media);
  }, [tripId]);

  useEffect(() => {
    let cancelled = false;
    async function loadGuest() {
      try {
        const result = await api.guestMe();
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
        const result = await api.media(tripId);
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
      await api.completeUploadFile(uploadFile.id);
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
      const session = await api.createUploadSession(tripId, {
        files: files.map((file) => ({
          filename: file.name,
          byteSize: file.size,
          mimeType: file.type || "application/octet-stream",
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
    await api.cancelUploadFile(uploadFile.id);
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
    await api.updateMedia(item.id, { visibility });
    await loadContribution();
  }

  async function deleteOwnMedia(item: MediaItemResponse) {
    await api.updateMedia(item.id, { deleted: true });
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
                await api.retryMedia(item.id);
                await loadContribution();
              }}
              onVisibilityChange={updateOwnMedia}
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
  state,
  onStateChange,
  onMergeStops,
  onRenameStop,
  onSplitStop,
  mobilePane = "map",
  onMobilePaneChange,
  timezoneId,
}: {
  reconstruction: ReconstructionResponse | null;
  state: StoryMapState;
  onStateChange: (state: StoryMapState) => void;
  onMergeStops?: (sourceStopId: string, targetStopId: string) => Promise<void>;
  onRenameStop?: (stopId: string, title: string) => Promise<void>;
  onSplitStop?: (stopId: string, afterMomentId: string) => Promise<void>;
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
  const reducedMotion = useReducedMotion();
  const [galleryMediaId, setGalleryMediaId] = useState<string | null>(null);
  const [galleryPhotoIds, setGalleryPhotoIds] = useState<string[] | null>(null);
  const [editToolsStopId, setEditToolsStopId] = useState<string | null>(null);
  const [editingStopId, setEditingStopId] = useState<string | null>(null);
  const [stopTitleDraft, setStopTitleDraft] = useState("");
  const [renameStopError, setRenameStopError] = useState("");
  const [savingStopId, setSavingStopId] = useState<string | null>(null);
  const [mergeStopError, setMergeStopError] = useState("");
  const [mergingStopKey, setMergingStopKey] = useState<string | null>(null);
  const [pendingMergeKey, setPendingMergeKey] = useState<string | null>(null);
  const [splitStopId, setSplitStopId] = useState<string | null>(null);
  const [splitStopError, setSplitStopError] = useState("");
  const [splittingStopKey, setSplittingStopKey] = useState<string | null>(null);
  const [isPhotoRollOpen, setIsPhotoRollOpen] = useState(false);
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
    if (!galleryPhotoIds) {
      return galleryPhotos;
    }
    const scopedIds = new Set(galleryPhotoIds);
    return galleryPhotos.filter((photo) => scopedIds.has(photo.id));
  }, [galleryPhotoIds, galleryPhotos]);
  const photoRollDays = useMemo(
    () =>
      reconstruction?.days
        .filter((day) => !state.selectedDayId || day.id === state.selectedDayId)
        .map((day) => ({
          day,
          stops: day.stops
            .map((stop) => ({
              stop,
              photos: filteredModel.media
                .filter((item) => item.stopId === stop.id && item.thumbnailUrl)
                .map((item) =>
                  galleryPhotoFromStoryMedia(item, displayStopTitle(stop)),
                ),
            }))
            .filter((section) => section.photos.length > 0),
        }))
        .filter((day) => day.stops.length > 0) ?? [],
    [filteredModel.media, reconstruction?.days, state.selectedDayId],
  );
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
  const isPhotoRollVisible =
    isPhotoRollOpen || (mobilePane === "photos" && photoRollDays.length > 0);
  const closePhotoRoll = useCallback(() => {
    setIsPhotoRollOpen(false);
    if (mobilePane === "photos") {
      onMobilePaneChange?.("map");
    }
  }, [mobilePane, onMobilePaneChange]);

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
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (canSelectTimelineStop()) {
        onStateChange(selectStoryStop(state, stopId, dayId));
      }
    }
  }

  function openStopPhotos(stopId: string, dayId: string) {
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
    setGalleryPhotoIds(stopMedia.map((item) => item.id));
    setGalleryMediaId(featuredMedia.id);
  }

  function openPhotoRollPhoto(photoId: string, photoIds: string[]) {
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
    setGalleryPhotoIds(photoIds);
    setGalleryMediaId(photoId);
    closePhotoRoll();
  }

  function showDayStops(dayId: string) {
    skipNextTimelineSelectionRef.current = true;
    onStateChange({
      ...state,
      viewMode: "STOP",
      selectedDayId: dayId,
      selectedStopId: null,
      selectedMomentId: null,
      selectedMediaId: null,
      mapControlMode: "STORY_CONTROLLED",
    });
  }

  function displayStopTitle(
    stop: ReconstructionResponse["days"][number]["stops"][number],
  ): string {
    return stop.title ?? stop.placeName ?? `Stop ${stop.position}`;
  }

  function startRenamingStop(
    stop: ReconstructionResponse["days"][number]["stops"][number],
  ) {
    setEditToolsStopId(stop.id);
    setEditingStopId(stop.id);
    setStopTitleDraft(displayStopTitle(stop));
    setRenameStopError("");
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

  async function mergeAdjacentStop(
    sourceStopId: string,
    targetStopId: string,
    dayId: string,
    direction: "previous" | "next",
  ) {
    if (!onMergeStops) {
      return;
    }
    const key = `${sourceStopId}:${targetStopId}`;
    if (pendingMergeKey !== key) {
      setPendingMergeKey(key);
      setMergeStopError("");
      return;
    }
    setMergingStopKey(key);
    setMergeStopError("");
    try {
      await onMergeStops(sourceStopId, targetStopId);
      onStateChange(selectStoryStop(state, targetStopId, dayId));
      setPendingMergeKey(null);
      setEditToolsStopId(null);
    } catch (error) {
      setMergeStopError(
        `Could not merge ${direction} stop. ${messageFrom(error)}`,
      );
    } finally {
      setMergingStopKey(null);
    }
  }

  async function splitStopAfterMoment(
    stopId: string,
    afterMomentId: string,
    dayId: string,
  ) {
    if (!onSplitStop) {
      return;
    }
    const key = `${stopId}:${afterMomentId}`;
    setSplittingStopKey(key);
    setSplitStopError("");
    try {
      await onSplitStop(stopId, afterMomentId);
      onStateChange(selectStoryStop(state, stopId, dayId));
      setSplitStopId(null);
      setEditToolsStopId(null);
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
    ? displayStopTitle(selectedStopDetail)
    : (selectedStop?.label ?? null);
  const selectedStopSummary = selectedStopDetail
    ? selectedStopDetail.placeName &&
      selectedStopDetail.placeName !== selectedStopTitle
      ? selectedStopDetail.placeName
      : `${selectedStopDetail.mediaCount} photos · ${selectedStopDetail.contributorCount} travelers`
    : activeDay
      ? `${activeDay.stops.length} stops · ${activeDay.stops.reduce(
          (total, stop) => total + stop.mediaCount,
          0,
        )} photos`
      : "Select a stop on the map to see its note here.";

  return (
    <div
      className={`story-explorer story-shell story-mobile-pane-${displayMobilePane}`}
    >
      <div className="story-map-panel">
        <StoryMapCanvas
          model={filteredModel}
          state={state}
          onStateChange={onStateChange}
          onDayMarkerClick={showDayStops}
          onStopMarkerClick={openStopPhotos}
          reducedMotion={reducedMotion}
        />
      </div>

      <aside className="story-side-panel">
        <div className="story-panel-header">
          <div>
            <p className="eyebrow">
              {activeDay ? `Day ${activeDay.position}` : "Timeline"}
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
                Day {day.position}
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
        {photoRollDays.length > 0 ? (
          <div className="story-photo-roll-launch">
            <div>
              <strong>
                {activeDay
                  ? `${activeDay.title ?? `Day ${activeDay.position}`} photos`
                  : "Trip photos"}
              </strong>
              <span>{photoRollPhotoCount} photos grouped by stop</span>
            </div>
            <button type="button" onClick={() => setIsPhotoRollOpen(true)}>
              Browse day photos
            </button>
          </div>
        ) : null}
        <div className="story-selected-stop-summary" aria-live="polite">
          <div>
            <span>
              {selectedStop
                ? "Selected stop"
                : activeDay
                  ? "Selected day"
                  : "Map note"}
            </span>
            <strong>
              {selectedStopTitle
                ? selectedStopTitle
                : activeDay
                  ? (activeDay.title ?? `Day ${activeDay.position}`)
                  : "No stop selected"}
            </strong>
            <p>{selectedStopSummary}</p>
          </div>
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
        <section
          className="story-timeline"
          aria-label="Chronological timeline"
          ref={timelineRef}
        >
          <p className="screen-reader-map-summary">
            Map alternative: {filteredModel.stops.length} stops,{" "}
            {filteredModel.media.length} photos, selected {selectedLabel}.
          </p>
          {story.days.map((day) => (
            <article
              className={`timeline-day ${
                state.selectedDayId === day.id ? "active" : ""
              }`}
              key={day.id}
            >
              <button
                type="button"
                className="timeline-day-button"
                onClick={() => onStateChange(selectStoryDay(state, day.id))}
              >
                <span>{day.title ?? `Day ${day.position}`}</span>
                <small>{day.date}</small>
              </button>
              {day.stops.map((stop, stopIndex) => {
                const previousStop = day.stops[stopIndex - 1] ?? null;
                const nextStop = day.stops[stopIndex + 1] ?? null;
                const isEditingTools = editToolsStopId === stop.id;
                return (
                  <section
                    className={`timeline-stop ${
                      state.selectedStopId === stop.id ? "active" : ""
                    }`}
                    data-day-id={day.id}
                    data-stop-id={stop.id}
                    key={stop.id}
                    ref={(element) => {
                      activeStopRefs.current[stop.id] = element;
                    }}
                    tabIndex={canSelectTimelineStop() ? 0 : -1}
                    onFocus={() => {
                      if (canSelectTimelineStop()) {
                        onStateChange(selectStoryStop(state, stop.id, day.id));
                      }
                    }}
                    onKeyDown={(event) =>
                      handleTimelineKey(event, stop.id, day.id)
                    }
                  >
                    <span className="timeline-stop-time">
                      {formatTimelineStopTime(
                        stop.startsAt,
                        stop.startsAtLocal ?? null,
                        timezoneId,
                      )}
                    </span>
                    <div className="timeline-stop-card">
                      <div className="timeline-stop-heading">
                        <button
                          type="button"
                          className="timeline-stop-button"
                          disabled={!canSelectTimelineStop()}
                          onClick={() =>
                            onStateChange(
                              selectStoryStop(state, stop.id, day.id),
                            )
                          }
                        >
                          <span>{displayStopTitle(stop)}</span>
                          <small>
                            {stop.mediaCount} photos · {stop.contributorCount}{" "}
                            travelers
                          </small>
                        </button>
                        {onRenameStop || onMergeStops || onSplitStop ? (
                          <button
                            type="button"
                            className="timeline-stop-edit"
                            aria-expanded={isEditingTools}
                            onClick={() => {
                              const nextStopId = isEditingTools
                                ? null
                                : stop.id;
                              setEditToolsStopId(nextStopId);
                              setEditingStopId(null);
                              setStopTitleDraft("");
                              setRenameStopError("");
                              setMergeStopError("");
                              setPendingMergeKey(null);
                              setSplitStopId(null);
                              setSplitStopError("");
                            }}
                          >
                            {isEditingTools ? "Done" : "Edit"}
                          </button>
                        ) : null}
                      </div>
                      {isEditingTools ? (
                        <div className="timeline-stop-edit-panel">
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
                                  maxLength={255}
                                  required
                                />
                              </label>
                              <div className="button-row">
                                <button
                                  type="submit"
                                  disabled={
                                    savingStopId === stop.id ||
                                    !stopTitleDraft.trim()
                                  }
                                >
                                  Save
                                </button>
                                <button
                                  type="button"
                                  className="secondary-button"
                                  onClick={() => {
                                    setEditingStopId(null);
                                    setStopTitleDraft("");
                                    setRenameStopError("");
                                  }}
                                >
                                  Cancel
                                </button>
                              </div>
                              {renameStopError ? (
                                <p className="error">{renameStopError}</p>
                              ) : null}
                            </form>
                          ) : onRenameStop ? (
                            <button
                              type="button"
                              className="timeline-stop-edit"
                              onClick={() => startRenamingStop(stop)}
                            >
                              Rename
                            </button>
                          ) : null}
                          {onMergeStops && (previousStop || nextStop) ? (
                            <div className="timeline-stop-merge">
                              {previousStop ? (
                                <button
                                  type="button"
                                  className="secondary-button"
                                  disabled={
                                    mergingStopKey ===
                                    `${previousStop.id}:${stop.id}`
                                  }
                                  onClick={() =>
                                    void mergeAdjacentStop(
                                      previousStop.id,
                                      stop.id,
                                      day.id,
                                      "previous",
                                    )
                                  }
                                >
                                  {pendingMergeKey ===
                                  `${previousStop.id}:${stop.id}`
                                    ? "Confirm merge previous"
                                    : "Merge previous"}
                                </button>
                              ) : null}
                              {nextStop ? (
                                <button
                                  type="button"
                                  className="secondary-button"
                                  disabled={
                                    mergingStopKey ===
                                    `${nextStop.id}:${stop.id}`
                                  }
                                  onClick={() =>
                                    void mergeAdjacentStop(
                                      nextStop.id,
                                      stop.id,
                                      day.id,
                                      "next",
                                    )
                                  }
                                >
                                  {pendingMergeKey ===
                                  `${nextStop.id}:${stop.id}`
                                    ? "Confirm merge next"
                                    : "Merge next"}
                                </button>
                              ) : null}
                              {pendingMergeKey ? (
                                <p className="timeline-stop-edit-hint">
                                  Merge combines two stops. Click confirm to
                                  continue.
                                </p>
                              ) : null}
                              {mergeStopError ? (
                                <p className="error">{mergeStopError}</p>
                              ) : null}
                            </div>
                          ) : null}
                          {onSplitStop && stop.moments.length > 1 ? (
                            <div className="timeline-stop-split">
                              <button
                                type="button"
                                className="secondary-button"
                                onClick={() => {
                                  setSplitStopId(
                                    splitStopId === stop.id ? null : stop.id,
                                  );
                                  setSplitStopError("");
                                }}
                              >
                                {splitStopId === stop.id
                                  ? "Cancel split"
                                  : "Split stop"}
                              </button>
                              {splitStopId === stop.id ? (
                                <div className="timeline-stop-split-panel">
                                  <p>
                                    Pick the last photo group that should stay
                                    in {displayStopTitle(stop)}.
                                  </p>
                                  {stop.moments.slice(0, -1).map((moment) => {
                                    const splitKey = `${stop.id}:${moment.id}`;
                                    return (
                                      <div
                                        className="timeline-stop-split-option"
                                        key={moment.id}
                                      >
                                        <div>
                                          <strong>
                                            {formatTimelineStopTime(
                                              moment.endsAt,
                                              moment.endsAtLocal ?? null,
                                              timezoneId,
                                            )}
                                          </strong>
                                          <span>
                                            {moment.mediaCount} photos before
                                            split
                                          </span>
                                          <div
                                            className="timeline-stop-split-thumbs"
                                            aria-hidden="true"
                                          >
                                            {moment.media
                                              .slice(0, 4)
                                              .map((item) =>
                                                item.thumbnailUrl ? (
                                                  <img
                                                    key={item.id}
                                                    src={item.thumbnailUrl}
                                                    alt=""
                                                    loading="lazy"
                                                  />
                                                ) : (
                                                  <span key={item.id}>
                                                    {item.contributor
                                                      .slice(0, 1)
                                                      .toUpperCase()}
                                                  </span>
                                                ),
                                              )}
                                          </div>
                                        </div>
                                        <button
                                          type="button"
                                          className="secondary-button"
                                          disabled={
                                            splittingStopKey === splitKey
                                          }
                                          onClick={() =>
                                            void splitStopAfterMoment(
                                              stop.id,
                                              moment.id,
                                              day.id,
                                            )
                                          }
                                        >
                                          Split here
                                        </button>
                                      </div>
                                    );
                                  })}
                                  {splitStopError ? (
                                    <p className="error">{splitStopError}</p>
                                  ) : null}
                                </div>
                              ) : null}
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  </section>
                );
              })}
            </article>
          ))}
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
                    ? `${activeDay.title ?? `Day ${activeDay.position}`} photos`
                    : "Trip photos"}
                </h3>
                <span>{photoRollPhotoCount} photos grouped by stop</span>
              </div>
              <button type="button" onClick={closePhotoRoll}>
                Close
              </button>
            </div>
            <div className="story-photo-roll" aria-label="Photos by stop">
              {photoRollDays.map(({ day, stops }) => (
                <div className="story-photo-roll-day" key={day.id}>
                  {!activeDay ? (
                    <strong className="story-photo-roll-day-title">
                      {day.title ?? `Day ${day.position}`}
                    </strong>
                  ) : null}
                  {stops.map(({ stop, photos }) => {
                    const dayPhotoIds = stops.flatMap((section) =>
                      section.photos.map((photo) => photo.id),
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
                                openPhotoRollPhoto(photo.id, dayPhotoIds)
                              }
                            >
                              {photo.imageUrl ? (
                                <img
                                  src={photo.imageUrl}
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
    imageUrl: item.thumbnailUrl,
    filename: item.filename,
    contributor: item.contributor,
    capturedAt: item.capturedAt,
    contextLabel,
  };
}

function galleryPhotoFromMediaItem(item: MediaItemResponse): GalleryPhoto {
  return {
    id: item.id,
    imageUrl: item.thumbnail?.downloadUrl ?? null,
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
          <button type="button" onClick={onClose}>
            Close
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
                {photo.imageUrl ? (
                  <img src={photo.imageUrl} alt="" loading="lazy" />
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
) {
  let selectedMarkerAnchor: HTMLElement | null = null;
  for (const marker of markers) {
    const markerAnchor = marker.getElement();
    const dayMarker = markerAnchor.querySelector(".photo-day-marker");
    const stopMarker = markerAnchor.querySelector(".photo-stop-marker");
    const isSelected =
      (dayMarker !== null && markerAnchor.dataset.dayId === selectedDayId) ||
      (stopMarker !== null && markerAnchor.dataset.stopId === selectedStopId);
    markerAnchor.classList.toggle("selected", isSelected);
    markerAnchor.style.zIndex = isSelected ? "30" : "";
    dayMarker?.classList.toggle("active", isSelected);
    stopMarker?.classList.toggle("active", isSelected);
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
  onStateChange,
  onDayMarkerClick,
  onStopMarkerClick,
  reducedMotion,
}: {
  model: ReturnType<typeof buildStoryModel>;
  state: StoryMapState;
  onStateChange: (state: StoryMapState) => void;
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

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const dayColorMap = useMemo(() => storyDayColorMap(model), [model]);
  const routeCollection = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: model.legs
        .filter((leg) => leg.geometry)
        .map((leg) => ({
          type: "Feature" as const,
          id: leg.id,
          properties: {
            id: leg.id,
            dayId: leg.dayId,
            dayColor: dayColorMap.get(leg.dayId) ?? storyDayColors[0],
            routeSource: leg.routeSource,
          },
          geometry: leg.geometry,
        })),
    }),
    [dayColorMap, model.legs],
  );
  const stopDisplayCoordinates = useMemo(
    () => stopDisplayCoordinateMap(model),
    [model],
  );
  const stopCollection = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: model.stops
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
    [dayColorMap, model.stops, stopDisplayCoordinates],
  );
  const mediaCollection = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: model.media
        .filter((item) => item.coordinates)
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
    [dayColorMap, model.media, state.selectedMediaId],
  );
  const hasMapData =
    routeCollection.features.length > 0 ||
    stopCollection.features.length > 0 ||
    mediaCollection.features.length > 0;
  const mapDataRef = useRef({
    mediaCollection,
    routeCollection,
    stopCollection,
  });

  useEffect(() => {
    mapDataRef.current = {
      mediaCollection,
      routeCollection,
      stopCollection,
    };
  }, [mediaCollection, routeCollection, stopCollection]);
  const canReturnToDayMode =
    Boolean(state.selectedDayId) &&
    !["TRIP_OVERVIEW", "DAY"].includes(state.viewMode);
  const dayMarkerData = useMemo(
    () =>
      Array.from(new Set(model.stops.map((stop) => stop.dayId)))
        .map((dayId, index) => {
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
          return {
            dayId,
            label: firstStop ? `Day ${index + 1}` : "Day",
            coordinates,
            featuredMedia,
            count: dayStops.length,
            color: dayColorMap.get(dayId) ?? storyDayColors[0],
          };
        })
        .filter((item) => item.coordinates),
    [dayColorMap, model.media, model.stops, stopDisplayCoordinates],
  );
  const displayStopOrder = useMemo(() => {
    const order = new Map<string, { position: number; count: number }>();
    const dayIds = Array.from(new Set(model.stops.map((stop) => stop.dayId)));
    for (const dayId of dayIds) {
      const dayStops = model.stops.filter((stop) => stop.dayId === dayId);
      dayStops.forEach((stop, index) => {
        order.set(stop.id, { position: index + 1, count: dayStops.length });
      });
    }
    return order;
  }, [model.stops]);
  const stopMarkerData = useMemo(
    () =>
      model.stops
        .filter(
          (stop) =>
            state.viewMode !== "STOP" ||
            !state.selectedDayId ||
            stop.dayId === state.selectedDayId,
        )
        .map((stop) => {
          const coordinates = stopDisplayCoordinates.get(stop.id) ?? null;
          const stopMedia = model.media.filter(
            (item) => item.stopId === stop.id,
          );
          const featuredMedia =
            stopMedia.find((item) => item.thumbnailUrl) ?? stopMedia[0] ?? null;
          const order = displayStopOrder.get(stop.id);
          const displayPosition = order?.position ?? stop.position;
          const displayCount = order?.count ?? 1;
          return {
            stop,
            coordinates,
            featuredMedia,
            count: stopMedia.length,
            flowLabel:
              displayPosition === 1
                ? "Start"
                : displayPosition === displayCount
                  ? "End"
                  : String(displayPosition),
            flowTone:
              displayPosition === 1
                ? "start"
                : displayPosition === displayCount
                  ? "end"
                  : "step",
            color: dayColorMap.get(stop.dayId) ?? storyDayColors[0],
          };
        }),
    [
      dayColorMap,
      displayStopOrder,
      model.media,
      model.stops,
      state.selectedDayId,
      state.viewMode,
      stopDisplayCoordinates,
    ],
  );
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
  const showDayMarkers =
    state.viewMode === "DAY" || state.viewMode === "TRIP_OVERVIEW";

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
      (map.getSource("trip-routes") as GeoJSONSource | undefined)?.setData(
        mapDataRef.current.routeCollection,
      );
      (map.getSource("trip-stops") as GeoJSONSource | undefined)?.setData(
        mapDataRef.current.stopCollection,
      );
      (map.getSource("trip-media") as GeoJSONSource | undefined)?.setData(
        mapDataRef.current.mediaCollection,
      );
      map.addLayer({
        id: "routes-confirmed",
        type: "line",
        source: "trip-routes",
        filter: ["!=", ["get", "routeSource"], "photo_inferred"],
        paint: {
          "line-color": ["get", "dayColor"],
          "line-width": 4,
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
          "line-width": 3.4,
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
  }, [mediaCollection, routeCollection, stopCollection]);

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
        count,
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
        if (count > 1) {
          const badge = document.createElement("small");
          badge.textContent = `${count} stops`;
          element.appendChild(badge);
        }
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
      return () => {
        stopPhotoMarkers.current.forEach((marker) => marker.remove());
        stopPhotoMarkers.current = [];
      };
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
        fallback.textContent = String(stop.position);
        mediaFrame.appendChild(fallback);
      }
      bubble.appendChild(mediaFrame);
      const badge = document.createElement("small");
      badge.className = `photo-stop-flow-badge ${flowTone}`;
      badge.textContent = flowLabel;
      bubble.appendChild(badge);
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
    return () => {
      stopPhotoMarkers.current.forEach((marker) => marker.remove());
      stopPhotoMarkers.current = [];
    };
  }, [
    onDayMarkerClick,
    onStopMarkerClick,
    orderedDayMarkerData,
    orderedStopMarkerData,
    showDayMarkers,
  ]);

  useEffect(() => {
    syncStoryMapMarkerSelection(
      stopPhotoMarkers.current,
      state.selectedDayId,
      state.selectedStopId,
    );
  }, [state.selectedDayId, state.selectedStopId]);

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
    const coordinates = focusCoordinates(model, state, stopDisplayCoordinates);
    if (coordinates.length === 0) {
      return;
    }
    if (state.viewMode === "STOP" && state.selectedStopId) {
      const previousFocus = previousFocusRef.current;
      previousFocusRef.current = {
        selectedStopId: state.selectedStopId,
        viewMode: state.viewMode,
      };
      if (
        previousFocus.viewMode === "STOP" &&
        previousFocus.selectedStopId &&
        previousFocus.selectedStopId !== state.selectedStopId
      ) {
        if (map.getZoom() < 12) {
          map.easeTo({
            center: coordinates[0],
            zoom: 13,
            duration: reducedMotion ? 0 : 360,
          });
          return;
        }
        map.panTo(coordinates[0], {
          duration: reducedMotion ? 0 : 360,
        });
        return;
      }
      map.easeTo({
        center: coordinates[0],
        zoom: Math.max(map.getZoom(), 13),
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
  }, [model, reducedMotion, state, stopDisplayCoordinates]);

  return (
    <div
      className={`story-map-shell ${
        hasConfiguredMapStyle() ? "configured-map-shell" : "local-map-shell"
      }`}
    >
      <div className="story-map" ref={mapNode} aria-hidden="true" />
      {canReturnToDayMode && state.selectedDayId ? (
        <button
          type="button"
          className="map-day-return"
          onClick={() =>
            onStateChange(selectStoryDay(state, state.selectedDayId as string))
          }
        >
          Day view
        </button>
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
  if (files.length === 0) {
    return <p>No uploads yet.</p>;
  }
  return (
    <div className="upload-list" role="list">
      {files.map((file) => {
        const itemProgress = progress[file.id];
        const loaded = itemProgress?.loaded ?? 0;
        const total = itemProgress?.total ?? file.byteSize ?? 0;
        const status = itemProgress?.status ?? file.state;
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
            ) : null}
          </div>
        );
      })}
    </div>
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

function PublicStoryViewer({ token }: { token: string }) {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [story, setStory] = useState<PublicStoryResponse | null>(null);
  const [error, setError] = useState("");
  const [storyState, setStoryState] = useState<StoryMapState>(() =>
    initialStoryMapState(),
  );
  const [mobilePane, setMobilePane] = useState<StoryMobilePane>("map");

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
        </nav>
      </header>
      <TripStoryExplorer
        reconstruction={story.story}
        state={storyState}
        onStateChange={setStoryState}
        mobilePane={mobilePane}
        onMobilePaneChange={setMobilePane}
        timezoneId={timezoneId}
      />
    </main>
  );
}

function StoryHeaderIcon({ action }: { action: StoryMobilePane }) {
  if (action === "map") {
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
                  <strong>
                    {stop.title ?? `Stop ${stop.position}`}
                    {stop.placeName ? ` · ${stop.placeName}` : ""}
                  </strong>
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
  onDelete,
  timezoneId,
}: {
  media: MediaItemResponse[];
  onRetry: (item: MediaItemResponse) => void;
  onVisibilityChange?: (item: MediaItemResponse, visibility: string) => void;
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
    trip: "Trip members",
    story: "Publishable",
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
                {item.includeInStory ? " · included in story" : ""}
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
              {item.processingState === "failed" ? (
                <button type="button" onClick={() => onRetry(item)}>
                  Retry processing
                </button>
              ) : null}
              {onVisibilityChange ? (
                <div className="button-row">
                  <button
                    type="button"
                    className={item.visibility === "trip" ? "active" : ""}
                    aria-pressed={item.visibility === "trip"}
                    onClick={() => onVisibilityChange(item, "trip")}
                  >
                    Trip members
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
                    Publishable
                  </button>
                  <button
                    type="button"
                    className={item.visibility === "private" ? "active" : ""}
                    aria-pressed={item.visibility === "private"}
                    onClick={() => onVisibilityChange(item, "private")}
                  >
                    Private
                  </button>
                  <button
                    type="button"
                    className={item.visibility === "excluded" ? "active" : ""}
                    aria-pressed={item.visibility === "excluded"}
                    onClick={() => onVisibilityChange(item, "excluded")}
                  >
                    Exclude
                  </button>
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
