import type {
  AuthResponse,
  GuestMemberResponse,
  InvitationAcceptRequest,
  InvitationCreateRequest,
  InvitationPreviewResponse,
  InvitationResponse,
  InvitationsListResponse,
  LoginRequest,
  MediaUpdateRequest,
  MediaItemResponse,
  MediaListResponse,
  MemberRosterResponse,
  MeResponse,
  PublicationResponse,
  PublicationsListResponse,
  PublicStoryResponse,
  ReconstructionResponse,
  RegisterRequest,
  SimilarityGroupsResponse,
  TripCreateRequest,
  TripResponse,
  TripsListResponse,
  TripUpdateRequest,
  CompleteUploadFileResponse,
  EditOperationRequest,
  EditOperationResponse,
  UploadSessionCreateRequest,
  UploadSessionResponse,
  UploadSessionsListResponse,
} from "./api-types";

const DEFAULT_API_BASE_URL = "http://localhost:8000";

export function resolveApiBaseUrl(
  configuredBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ??
    DEFAULT_API_BASE_URL,
  browserLocation: Location | undefined = typeof window === "undefined"
    ? undefined
    : window.location,
): string {
  if (!browserLocation) {
    return configuredBaseUrl;
  }
  try {
    const apiUrl = new URL(configuredBaseUrl);
    const pageHost = browserLocation.hostname;
    const apiHost = apiUrl.hostname;
    const apiIsLoopback =
      apiHost === "localhost" || apiHost === "127.0.0.1" || apiHost === "::1";
    const pageIsLoopback =
      pageHost === "localhost" ||
      pageHost === "127.0.0.1" ||
      pageHost === "::1";
    if (apiIsLoopback && !pageIsLoopback) {
      apiUrl.hostname = pageHost;
      return apiUrl.toString().replace(/\/$/, "");
    }
  } catch {
    return configuredBaseUrl;
  }
  return configuredBaseUrl;
}

const API_BASE_URL = resolveApiBaseUrl();

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

function withGuestActor(options: RequestInit = {}): RequestInit {
  const headers = new Headers(options.headers);
  headers.set("x-tripweave-actor", "guest");
  return { ...options, headers };
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
  guestMe(): Promise<GuestMemberResponse> {
    return apiRequest<GuestMemberResponse>("/guest/me");
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
  createInvitation(
    tripId: string,
    payload: InvitationCreateRequest = {},
  ): Promise<InvitationResponse> {
    return apiRequest<InvitationResponse>(`/trips/${tripId}/invitations`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  invitations(tripId: string): Promise<InvitationsListResponse> {
    return apiRequest<InvitationsListResponse>(`/trips/${tripId}/invitations`);
  },
  revokeInvitation(id: string): Promise<void> {
    return apiRequest<void>(`/invitations/${id}`, { method: "DELETE" });
  },
  previewInvitation(token: string): Promise<InvitationPreviewResponse> {
    return apiRequest<InvitationPreviewResponse>(
      `/invitations/${encodeURIComponent(token)}`,
    );
  },
  acceptInvitation(
    token: string,
    payload: InvitationAcceptRequest,
  ): Promise<GuestMemberResponse> {
    return apiRequest<GuestMemberResponse>(
      `/invitations/${encodeURIComponent(token)}/accept`,
      { method: "POST", body: JSON.stringify(payload) },
    );
  },
  members(tripId: string): Promise<MemberRosterResponse> {
    return apiRequest<MemberRosterResponse>(`/trips/${tripId}/members`);
  },
  removeMember(id: string): Promise<void> {
    return apiRequest<void>(`/trip-members/${id}`, { method: "DELETE" });
  },
  media(tripId: string): Promise<MediaListResponse> {
    return apiRequest<MediaListResponse>(`/trips/${tripId}/media`);
  },
  similarityGroups(tripId: string): Promise<SimilarityGroupsResponse> {
    return apiRequest<SimilarityGroupsResponse>(
      `/trips/${tripId}/similarity-groups`,
    );
  },
  reconstruction(tripId: string): Promise<ReconstructionResponse> {
    return apiRequest<ReconstructionResponse>(
      `/trips/${tripId}/reconstruction`,
    );
  },
  startReconstruction(tripId: string): Promise<ReconstructionResponse> {
    return apiRequest<ReconstructionResponse>(
      `/trips/${tripId}/reconstruction-runs`,
      { method: "POST" },
    );
  },
  createEditOperation(
    tripId: string,
    payload: EditOperationRequest,
  ): Promise<EditOperationResponse> {
    return apiRequest<EditOperationResponse>(
      `/trips/${tripId}/edit-operations`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    );
  },
  undoLatestEdit(tripId: string): Promise<EditOperationResponse> {
    return apiRequest<EditOperationResponse>(
      `/trips/${tripId}/edit-operations/undo`,
      { method: "POST" },
    );
  },
  publishTrip(tripId: string): Promise<PublicationResponse> {
    return apiRequest<PublicationResponse>(`/trips/${tripId}/publications`, {
      method: "POST",
    });
  },
  publications(tripId: string): Promise<PublicationsListResponse> {
    return apiRequest<PublicationsListResponse>(
      `/trips/${tripId}/publications`,
    );
  },
  revokeShareLink(id: string): Promise<void> {
    return apiRequest<void>(`/share-links/${id}`, { method: "DELETE" });
  },
  unpublishTrip(tripId: string): Promise<void> {
    return apiRequest<void>(`/trips/${tripId}/unpublish`, { method: "POST" });
  },
  publicStory(token: string): Promise<PublicStoryResponse> {
    return apiRequest<PublicStoryResponse>(
      `/public/shares/${encodeURIComponent(token)}`,
    );
  },
  updateMedia(
    id: string,
    payload: MediaUpdateRequest,
  ): Promise<MediaItemResponse> {
    return apiRequest<MediaItemResponse>(`/media/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },
  retryMedia(id: string): Promise<MediaItemResponse> {
    return apiRequest<MediaItemResponse>(`/media/${id}/retry`, {
      method: "POST",
    });
  },
  createUploadSession(
    tripId: string,
    payload: UploadSessionCreateRequest,
  ): Promise<UploadSessionResponse> {
    return apiRequest<UploadSessionResponse>(
      `/trips/${tripId}/upload-sessions`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    );
  },
  uploadSessions(tripId: string): Promise<UploadSessionsListResponse> {
    return apiRequest<UploadSessionsListResponse>(
      `/upload-sessions?trip_id=${encodeURIComponent(tripId)}`,
    );
  },
  completeUploadFile(id: string): Promise<CompleteUploadFileResponse> {
    return apiRequest<CompleteUploadFileResponse>(
      `/upload-files/${id}/complete`,
      { method: "POST" },
    );
  },
  cancelUploadFile(id: string): Promise<void> {
    return apiRequest<void>(`/upload-files/${id}`, { method: "DELETE" });
  },
};

export const guestApi = {
  guestMe(): Promise<GuestMemberResponse> {
    return apiRequest<GuestMemberResponse>("/guest/me", withGuestActor());
  },
  media(tripId: string): Promise<MediaListResponse> {
    return apiRequest<MediaListResponse>(
      `/trips/${tripId}/media`,
      withGuestActor(),
    );
  },
  updateMedia(
    id: string,
    payload: MediaUpdateRequest,
  ): Promise<MediaItemResponse> {
    return apiRequest<MediaItemResponse>(
      `/media/${id}`,
      withGuestActor({
        method: "PATCH",
        body: JSON.stringify(payload),
      }),
    );
  },
  retryMedia(id: string): Promise<MediaItemResponse> {
    return apiRequest<MediaItemResponse>(
      `/media/${id}/retry`,
      withGuestActor({ method: "POST" }),
    );
  },
  createUploadSession(
    tripId: string,
    payload: UploadSessionCreateRequest,
  ): Promise<UploadSessionResponse> {
    return apiRequest<UploadSessionResponse>(
      `/trips/${tripId}/upload-sessions`,
      withGuestActor({
        method: "POST",
        body: JSON.stringify(payload),
      }),
    );
  },
  uploadSessions(tripId: string): Promise<UploadSessionsListResponse> {
    return apiRequest<UploadSessionsListResponse>(
      `/upload-sessions?trip_id=${encodeURIComponent(tripId)}`,
      withGuestActor(),
    );
  },
  completeUploadFile(id: string): Promise<CompleteUploadFileResponse> {
    return apiRequest<CompleteUploadFileResponse>(
      `/upload-files/${id}/complete`,
      withGuestActor({ method: "POST" }),
    );
  },
  cancelUploadFile(id: string): Promise<void> {
    return apiRequest<void>(
      `/upload-files/${id}`,
      withGuestActor({ method: "DELETE" }),
    );
  },
};

export function uploadWithProgress({
  url,
  file,
  headers,
  onProgress,
}: {
  url: string;
  file: File;
  headers: Record<string, string>;
  onProgress: (loaded: number, total: number) => void;
}): { promise: Promise<void>; abort: () => void } {
  const request = new XMLHttpRequest();
  const promise = new Promise<void>((resolve, reject) => {
    request.open("PUT", url);
    for (const [name, value] of Object.entries(headers)) {
      request.setRequestHeader(name, value);
    }
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress(event.loaded, event.total);
      }
    };
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        resolve();
        return;
      }
      reject(
        new ApiError(request.responseText || "Upload failed", request.status),
      );
    };
    request.onerror = () => reject(new Error("Upload failed"));
    request.onabort = () => reject(new Error("Upload cancelled"));
    request.send(file);
  });
  return {
    promise,
    abort: () => request.abort(),
  };
}
