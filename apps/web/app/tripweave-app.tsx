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
  ReconstructionResponse,
  TripResponse,
  UploadFileResponse,
  UploadSessionResponse,
  UserResponse,
} from "./api-types";
import {
  EVERYONE,
  StoryMapState,
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
  selectStoryMoment,
  selectStoryStop,
  setContributorFilter,
  startPlayback,
} from "./story-map-state";

type AuthMode = "login" | "register";
type LoadState = "loading" | "ready";

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
  const [latestInviteUrl, setLatestInviteUrl] = useState("");
  const [latestInviteQrUrl, setLatestInviteQrUrl] = useState("");
  const [uploadProgress, setUploadProgress] = useState<
    Record<string, UploadProgress>
  >({});
  const localFiles = useRef<Map<string, File>>(new Map());
  const abortUpload = useRef<Map<string, () => void>>(new Map());

  const selectedTrip = useMemo(
    () => trips.find((trip) => trip.id === selectedTripId) ?? trips[0] ?? null,
    [selectedTripId, trips],
  );

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
      return;
    }
    const result = await api.media(tripId);
    setMedia(result.media);
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

  function selectTrip(trip: TripResponse) {
    setSelectedTripId(trip.id);
    setSettingsForm(fromTrip(trip));
    void loadUploadSessions(trip.id);
    void loadMedia(trip.id);
    void loadReconstruction(trip.id);
    void loadCollaboration(trip.id);
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
      setReconstruction(null);
      setInvitations([]);
      setMembers([]);
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
  }, [hasProcessingMedia, selectedTrip?.id]);

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
      setInvitations([]);
      setMembers([]);
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

  if (loadState === "loading") {
    return (
      <main className="app-shell">
        <p className="eyebrow">TripWeave local MVP</p>
        <h1>Loading workspace</h1>
      </main>
    );
  }

  if (!user) {
    return (
      <main className="auth-shell">
        <section className="auth-panel" aria-labelledby="auth-title">
          <p className="eyebrow">TripWeave local MVP</p>
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
      <header className="app-header">
        <div>
          <p className="eyebrow">TripWeave local MVP</p>
          <h1>Trips</h1>
          <p>Signed in as {user.display_name}</p>
        </div>
        <button type="button" onClick={logout} disabled={isBusy}>
          Logout
        </button>
      </header>

      {tripError ? <p className="error">{tripError}</p> : null}

      <section className="workspace">
        <form
          className="panel stack"
          onSubmit={createTrip}
          aria-labelledby="create-title"
        >
          <h2 id="create-title">Create trip</h2>
          <TripFields form={createForm} onChange={setCreateForm} />
          <button type="submit" disabled={isBusy}>
            Create trip
          </button>
        </form>

        <section className="panel" aria-labelledby="trip-list-title">
          <h2 id="trip-list-title">Your trips</h2>
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

        <form
          className="panel stack"
          onSubmit={updateTrip}
          aria-labelledby="settings-title"
        >
          <h2 id="settings-title">Trip settings</h2>
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

        <section className="panel stack" aria-labelledby="uploads-title">
          <h2 id="uploads-title">Uploads</h2>
          {selectedTrip ? (
            <>
              <div
                className="drop-zone"
                onDragOver={(event) => event.preventDefault()}
                onDrop={onDrop}
              >
                <label>
                  Add JPEG or HEIC images
                  <input
                    accept=".jpg,.jpeg,.heic,image/jpeg,image/heic,image/heif"
                    multiple
                    type="file"
                    onChange={onFileInput}
                  />
                </label>
                <p>Drag files here or use the file picker.</p>
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
            </>
          ) : (
            <p>Create or select a trip before uploading.</p>
          )}
        </section>

        {selectedTrip?.role === "owner" ? (
          <section className="panel stack" aria-labelledby="sharing-title">
            <div>
              <h2 id="sharing-title">Travelers</h2>
              <p>Invite guest contributors and manage trip access.</p>
            </div>
            {collaborationError ? (
              <p className="error">{collaborationError}</p>
            ) : null}
            <div className="action-row">
              <button type="button" onClick={createInvite} disabled={isBusy}>
                Create contributor link
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
            <InvitationList invitations={invitations} onRevoke={revokeInvite} />
            <MemberRoster members={members} onRemove={removeMember} />
          </section>
        ) : null}

        {selectedTrip && ["owner", "editor"].includes(selectedTrip.role) ? (
          <section
            className="panel stack media-panel"
            aria-labelledby="reconstruction-title"
          >
            <div className="section-heading">
              <div>
                <h2 id="reconstruction-title">Reconstruction</h2>
                <p>
                  Build days, stops, moments, inferred legs, and review items.
                </p>
              </div>
              <button
                type="button"
                onClick={runReconstruction}
                disabled={isBusy}
              >
                Run reconstruction
              </button>
            </div>
            {reconstructionError ? (
              <p className="error">{reconstructionError}</p>
            ) : null}
            <TripStoryExplorer
              reconstruction={reconstruction}
              state={storyState}
              onStateChange={setStoryState}
              timezoneId={selectedTrip.timezoneId}
            />
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
              onUndo={undoLatestEdit}
            />
          </section>
        ) : null}

        <section
          className="panel stack media-panel"
          aria-labelledby="media-title"
        >
          <div>
            <h2 id="media-title">Media</h2>
            {hasProcessingMedia ? <p>Processing uploads...</p> : null}
          </div>
          {mediaError ? <p className="error">{mediaError}</p> : null}
          <MediaList
            media={media}
            onRetry={retryMedia}
            timezoneId={selectedTrip?.timezoneId}
          />
        </section>
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

const localMapStyle: maplibregl.StyleSpecification = {
  version: 8,
  glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
  sources: {},
  layers: [
    {
      id: "local-background",
      type: "background",
      paint: { "background-color": "#eef3f0" },
    },
  ],
};

function configuredMapStyle(): string | maplibregl.StyleSpecification {
  return process.env.NEXT_PUBLIC_TRIPWEAVE_MAP_STYLE_URL || localMapStyle;
}

function TripStoryExplorer({
  reconstruction,
  state,
  onStateChange,
  timezoneId,
}: {
  reconstruction: ReconstructionResponse | null;
  state: StoryMapState;
  onStateChange: (state: StoryMapState) => void;
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
  const skipNextTimelineScrollRef = useRef(false);
  const reducedMotion = useReducedMotion();

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
    if (!state.selectedStopId || reducedMotion) {
      return;
    }
    if (skipNextTimelineScrollRef.current) {
      skipNextTimelineScrollRef.current = false;
      return;
    }
    activeStopRefs.current[state.selectedStopId]?.scrollIntoView({
      behavior: "smooth",
      block: "nearest",
    });
  }, [reducedMotion, state.selectedStopId]);

  useEffect(() => {
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
        if (stopId && dayId && stopId !== currentState.selectedStopId) {
          skipNextTimelineScrollRef.current = true;
          onStateChange(selectStoryStop(currentState, stopId, dayId));
        }
      },
      { root: timeline, threshold: [0.35, 0.7] },
    );
    for (const element of elements) {
      observer.observe(element);
    }
    return () => observer.disconnect();
  }, [filteredModel.stops, onStateChange]);

  if (!reconstruction?.latestRun) {
    return (
      <div className="story-empty">
        <p>Run reconstruction to create the synchronized map and timeline.</p>
      </div>
    );
  }

  function setViewMode(viewMode: ViewMode) {
    if (viewMode === "PLAYBACK") {
      onStateChange(startPlayback(state));
    } else {
      onStateChange({ ...state, viewMode, mapControlMode: "STORY_CONTROLLED" });
    }
  }

  function handleTimelineKey(
    event: KeyboardEvent<HTMLElement>,
    stopId: string,
    dayId: string,
  ) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onStateChange(selectStoryStop(state, stopId, dayId));
    }
  }

  const selectedLabel =
    selectedMedia?.filename ?? selectedStop?.label ?? "Trip overview";

  return (
    <div className="story-explorer">
      <div className="story-toolbar" aria-label="Story controls">
        <div className="segmented-control" role="group" aria-label="View mode">
          {(
            ["TRIP_OVERVIEW", "DAY", "STOP", "MOMENT", "PLAYBACK"] as ViewMode[]
          ).map((viewMode) => (
            <button
              aria-pressed={state.viewMode === viewMode}
              className={state.viewMode === viewMode ? "active" : ""}
              key={viewMode}
              type="button"
              onClick={() => setViewMode(viewMode)}
            >
              {viewMode.replace("_", " ")}
            </button>
          ))}
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
        <button
          type="button"
          onClick={() => onStateChange(followStory(state))}
          disabled={state.mapControlMode === "STORY_CONTROLLED"}
        >
          Follow Story
        </button>
        <button
          type="button"
          onClick={() => onStateChange(advancePlayback(state, filteredModel))}
        >
          Play next
        </button>
      </div>

      <div className="story-layout">
        <StoryMapCanvas
          model={filteredModel}
          state={state}
          onStateChange={onStateChange}
          reducedMotion={reducedMotion}
        />
        <section
          className="story-timeline"
          aria-label="Chronological timeline"
          ref={timelineRef}
        >
          <p className="screen-reader-map-summary">
            Map alternative: {filteredModel.stops.length} stops,{" "}
            {filteredModel.media.length} media items, selected {selectedLabel}.
          </p>
          {reconstruction.days.map((day) => (
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
                {day.title ?? day.date}
              </button>
              {day.stops.map((stop) => (
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
                  tabIndex={0}
                  onFocus={() =>
                    onStateChange(selectStoryStop(state, stop.id, day.id))
                  }
                  onKeyDown={(event) =>
                    handleTimelineKey(event, stop.id, day.id)
                  }
                >
                  <button
                    type="button"
                    className="timeline-stop-button"
                    onClick={() =>
                      onStateChange(selectStoryStop(state, stop.id, day.id))
                    }
                  >
                    <span>
                      {stop.title ?? stop.placeName ?? `Stop ${stop.position}`}
                    </span>
                    <small>
                      {formatReconstructionTime(
                        stop.startsAt,
                        stop.startsAtLocal ?? null,
                        timezoneId,
                      )}{" "}
                      · {stop.mediaCount} media · {stop.contributorCount}{" "}
                      travelers
                    </small>
                  </button>
                  <div className="timeline-moments">
                    {stop.moments.map((moment) => (
                      <article
                        className={`timeline-moment ${
                          state.selectedMomentId === moment.id ? "active" : ""
                        }`}
                        key={moment.id}
                      >
                        <button
                          type="button"
                          onClick={() =>
                            onStateChange(
                              selectStoryMoment(
                                state,
                                moment.id,
                                stop.id,
                                day.id,
                              ),
                            )
                          }
                        >
                          {moment.title ?? `Moment ${moment.position}`} ·{" "}
                          {moment.contributorCount} perspectives
                        </button>
                        <div className="perspective-strip">
                          {moment.media.map((item) => (
                            <button
                              className={`perspective-thumb ${
                                state.selectedMediaId === item.id
                                  ? "active"
                                  : ""
                              }`}
                              key={item.id}
                              type="button"
                              onClick={() =>
                                onStateChange(
                                  selectStoryMedia(
                                    state,
                                    item.id,
                                    moment.id,
                                    stop.id,
                                    day.id,
                                  ),
                                )
                              }
                            >
                              {item.thumbnailUrl ? (
                                <img
                                  src={item.thumbnailUrl}
                                  alt={item.filename ?? "Trip photo"}
                                  loading="lazy"
                                />
                              ) : (
                                <span>{item.contributor.slice(0, 1)}</span>
                              )}
                            </button>
                          ))}
                        </div>
                      </article>
                    ))}
                  </div>
                </section>
              ))}
            </article>
          ))}
        </section>
      </div>
    </div>
  );
}

function StoryMapCanvas({
  model,
  state,
  onStateChange,
  reducedMotion,
}: {
  model: ReturnType<typeof buildStoryModel>;
  state: StoryMapState;
  onStateChange: (state: StoryMapState) => void;
  reducedMotion: boolean;
}) {
  const mapNode = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const selectedMarkers = useRef<Marker[]>([]);
  const stateRef = useRef(state);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

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
            routeSource: leg.routeSource,
          },
          geometry: leg.geometry,
        })),
    }),
    [model.legs],
  );
  const stopCollection = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: model.stops
        .filter((stop) => stop.coordinates)
        .map((stop) => ({
          type: "Feature" as const,
          id: stop.id,
          properties: {
            id: stop.id,
            dayId: stop.dayId,
            label: stop.label,
            selected: stop.id === state.selectedStopId,
          },
          geometry: {
            type: "Point" as const,
            coordinates: stop.coordinates as [number, number],
          },
        })),
    }),
    [model.stops, state.selectedStopId],
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
    [model.media, state.selectedMediaId],
  );

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
        routeCollection,
      );
      (map.getSource("trip-stops") as GeoJSONSource | undefined)?.setData(
        stopCollection,
      );
      (map.getSource("trip-media") as GeoJSONSource | undefined)?.setData(
        mediaCollection,
      );
      map.addLayer({
        id: "routes-confirmed",
        type: "line",
        source: "trip-routes",
        filter: ["!=", ["get", "routeSource"], "photo_inferred"],
        paint: {
          "line-color": "#174d43",
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
          "line-color": "#6e7f8f",
          "line-width": 3,
          "line-dasharray": [2, 2],
          "line-opacity": 0.75,
        },
      });
      map.addLayer({
        id: "media-clusters",
        type: "circle",
        source: "trip-media",
        filter: ["has", "point_count"],
        paint: {
          "circle-color": "#2457a6",
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
            "#23695b",
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
            "#17202a",
          ],
          "circle-radius": ["case", ["==", ["get", "selected"], true], 11, 8],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 2,
        },
      });
      map.on("click", "stops", (event) => {
        const feature = event.features?.[0];
        const stopId = feature?.properties?.id as string | undefined;
        const dayId = feature?.properties?.dayId as string | undefined;
        if (stopId && dayId) {
          onStateChange(selectStoryStop(stateRef.current, stopId, dayId));
        }
      });
      map.on("click", "media-unclustered", (event) => {
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
    });

    return () => {
      selectedMarkers.current.forEach((marker) => marker.remove());
      selectedMarkers.current = [];
      map.remove();
      mapRef.current = null;
    };
  }, [mediaCollection, onStateChange, routeCollection, stopCollection]);

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
    if (!map) {
      return;
    }
    selectedMarkers.current.forEach((marker) => marker.remove());
    selectedMarkers.current = [];
    const selectedStop = model.stops.find(
      (stop) => stop.id === state.selectedStopId,
    );
    const selectedMedia = model.media
      .filter(
        (item) =>
          item.id === state.selectedMediaId ||
          item.momentId === state.selectedMomentId,
      )
      .slice(0, 5);
    if (selectedStop?.coordinates) {
      selectedMarkers.current.push(
        new maplibregl.Marker({ color: "#9f2d20" })
          .setLngLat(selectedStop.coordinates)
          .addTo(map),
      );
    }
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
    state.selectedMediaId,
    state.selectedMomentId,
    state.selectedStopId,
  ]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || state.mapControlMode !== "STORY_CONTROLLED") {
      return;
    }
    const coordinates = focusCoordinates(model, state);
    if (coordinates.length === 0) {
      return;
    }
    const bounds = new LngLatBounds(coordinates[0], coordinates[0]);
    for (const coordinate of coordinates.slice(1)) {
      bounds.extend(coordinate);
    }
    if (coordinates.length === 1) {
      map.easeTo({
        center: coordinates[0],
        zoom: 14,
        duration: reducedMotion ? 0 : 600,
      });
    } else {
      map.fitBounds(bounds, {
        padding: 56,
        maxZoom: 14,
        duration: reducedMotion ? 0 : 700,
      });
    }
  }, [model, reducedMotion, state]);

  return (
    <div className="story-map-shell">
      <div className="story-map" ref={mapNode} aria-hidden="true" />
      <div className="map-mode-badge">
        {state.mapControlMode === "USER_CONTROLLED"
          ? "User controlled"
          : "Story controlled"}
      </div>
    </div>
  );
}

function focusCoordinates(
  model: ReturnType<typeof buildStoryModel>,
  state: StoryMapState,
): [number, number][] {
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
    const mediaCoordinates = model.media
      .filter(
        (item) => item.stopId === state.selectedStopId && item.coordinates,
      )
      .map((item) => item.coordinates as [number, number]);
    const stop = model.stops.find((item) => item.id === state.selectedStopId);
    return stop?.coordinates
      ? [stop.coordinates, ...mediaCoordinates]
      : mediaCoordinates;
  }
  if (state.selectedDayId) {
    return model.stops
      .filter((item) => item.dayId === state.selectedDayId && item.coordinates)
      .map((item) => item.coordinates as [number, number]);
  }
  return [
    ...model.stops
      .filter((item) => item.coordinates)
      .map((item) => item.coordinates as [number, number]),
    ...model.media
      .filter((item) => item.coordinates)
      .map((item) => item.coordinates as [number, number]),
  ];
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

function ReconstructionOutline({
  reconstruction,
  timezoneId,
  reviewIndex,
  onSkipReview,
  onResolveReview,
  onDismissReview,
  onUndo,
}: {
  reconstruction: ReconstructionResponse | null;
  timezoneId: string;
  reviewIndex: number;
  onSkipReview: () => void;
  onResolveReview: (id: string) => void;
  onDismissReview: (id: string) => void;
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
            <div className="button-row">
              <button
                type="button"
                onClick={() => onResolveReview(currentReview.id)}
              >
                Resolve
              </button>
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
  if (media.length === 0) {
    return <p>No processed media yet.</p>;
  }
  return (
    <div className="media-list" role="list">
      {media.map((item) => (
        <article className="media-row" key={item.id} role="listitem">
          <div className="thumb-frame">
            {item.thumbnail?.downloadUrl ? (
              <img src={item.thumbnail.downloadUrl} alt="" />
            ) : (
              <span>{item.processingState}</span>
            )}
          </div>
          <div className="media-details">
            <strong>{item.filename ?? "Untitled image"}</strong>
            <small>
              {item.processingState} · {item.contributor}
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
                  onClick={() => onVisibilityChange(item, "trip")}
                >
                  Trip members
                </button>
                <button
                  type="button"
                  onClick={() => onVisibilityChange(item, "story")}
                >
                  Publishable
                </button>
                <button
                  type="button"
                  onClick={() => onVisibilityChange(item, "private")}
                >
                  Private
                </button>
                <button
                  type="button"
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
