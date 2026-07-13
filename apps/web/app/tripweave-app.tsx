"use client";

import {
  ChangeEvent,
  DragEvent,
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ApiError, api, uploadWithProgress } from "./api-client";
import type {
  TripResponse,
  UploadFileResponse,
  UploadSessionResponse,
  UserResponse,
} from "./api-types";

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

const emptyTripForm: TripForm = {
  title: "",
  description: "",
  startDate: "",
  endDate: "",
  timezoneId: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
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

  function selectTrip(trip: TripResponse) {
    setSelectedTripId(trip.id);
    setSettingsForm(fromTrip(trip));
    void loadUploadSessions(trip.id);
  }

  function removeTripFromState(tripId: string) {
    const remaining = trips.filter((trip) => trip.id !== tripId);
    const nextTrip = remaining[0] ?? null;
    setTrips(remaining);
    setSelectedTripId(nextTrip?.id ?? null);
    setSettingsForm(nextTrip ? fromTrip(nextTrip) : emptyTripForm);
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
      </section>
    </main>
  );
}

function TripFields({
  form,
  onChange,
}: {
  form: TripForm;
  onChange: (form: TripForm) => void;
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
      <div className="field-grid">
        <label>
          Time zone
          <input
            value={form.timezoneId}
            onChange={(event) => setField("timezoneId", event.target.value)}
            required
          />
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
