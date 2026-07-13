"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "./api-client";
import type { TripResponse, UserResponse } from "./api-types";

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

  const selectedTrip = useMemo(
    () => trips.find((trip) => trip.id === selectedTripId) ?? trips[0] ?? null,
    [selectedTripId, trips],
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
    },
    [],
  );

  function selectTrip(trip: TripResponse) {
    setSelectedTripId(trip.id);
    setSettingsForm(fromTrip(trip));
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
