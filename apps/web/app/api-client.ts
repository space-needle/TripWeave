import type {
  AuthResponse,
  LoginRequest,
  MeResponse,
  RegisterRequest,
  TripCreateRequest,
  TripResponse,
  TripsListResponse,
  TripUpdateRequest,
} from "./api-types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

export function csrfTokenFromCookie(cookieSource = document.cookie): string {
  const cookie = cookieSource
    .split(";")
    .map((value) => value.trim())
    .find((value) => value.startsWith("tripweave_csrf="));
  return cookie ? decodeURIComponent(cookie.split("=").slice(1).join("=")) : "";
}

async function apiRequest<TResponse>(
  path: string,
  options: RequestInit = {},
): Promise<TResponse> {
  const method = options.method ?? "GET";
  const headers = new Headers(options.headers);
  if (!headers.has("content-type") && options.body) {
    headers.set("content-type", "application/json");
  }
  if (method !== "GET") {
    const csrfToken = csrfTokenFromCookie();
    if (csrfToken) {
      headers.set("x-csrf-token", csrfToken);
    }
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    method,
    headers,
    credentials: "include",
  });

  if (!response.ok) {
    let message = "Request failed";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        message = body.detail;
      }
    } catch {
      message = response.statusText || message;
    }
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) {
    return undefined as TResponse;
  }
  return (await response.json()) as TResponse;
}

export const api = {
  register(payload: RegisterRequest): Promise<AuthResponse> {
    return apiRequest<AuthResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  login(payload: LoginRequest): Promise<AuthResponse> {
    return apiRequest<AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  logout(): Promise<void> {
    return apiRequest<void>("/auth/logout", { method: "POST" });
  },
  me(): Promise<MeResponse> {
    return apiRequest<MeResponse>("/auth/me");
  },
  trips(): Promise<TripsListResponse> {
    return apiRequest<TripsListResponse>("/trips");
  },
  createTrip(payload: TripCreateRequest): Promise<TripResponse> {
    return apiRequest<TripResponse>("/trips", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  updateTrip(id: string, payload: TripUpdateRequest): Promise<TripResponse> {
    return apiRequest<TripResponse>(`/trips/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },
  deleteTrip(id: string): Promise<void> {
    return apiRequest<void>(`/trips/${id}`, { method: "DELETE" });
  },
};
