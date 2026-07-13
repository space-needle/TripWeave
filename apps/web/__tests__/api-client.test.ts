import { afterEach, describe, expect, it, vi } from "vitest";
import { api, csrfTokenFromCookie } from "../app/api-client";

describe("api client", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("reads the CSRF token from cookies", () => {
    expect(
      csrfTokenFromCookie("other=1; tripweave_csrf=abc123; theme=light"),
    ).toBe("abc123");
  });

  it("sends credentials and CSRF header for trip mutations", async () => {
    vi.stubGlobal("document", { cookie: "tripweave_csrf=csrf-value" });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "trip-id",
          title: "Kyoto",
          description: null,
          startDate: null,
          endDate: null,
          timezoneId: "Asia/Tokyo",
          dayCutoffHour: 4,
          status: "active",
          visibility: "private",
          role: "owner",
          createdAt: "2026-07-13T00:00:00Z",
          updatedAt: "2026-07-13T00:00:00Z",
        }),
        { status: 201, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.createTrip({ title: "Kyoto", timezoneId: "Asia/Tokyo" });

    const [, options] = fetchMock.mock.calls[0];
    expect(options.credentials).toBe("include");
    expect(options.method).toBe("POST");
    expect((options.headers as Headers).get("x-csrf-token")).toBe("csrf-value");
  });
});
