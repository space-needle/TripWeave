import { describe, expect, it } from "vitest";
import { buildStatusItems } from "../app/status";

describe("buildStatusItems", () => {
  it("marks every dependency healthy when the backend reports healthy checks", () => {
    const items = buildStatusItems({
      api: { ok: true },
      database: { ok: true },
      postgis: { ok: true, version: "3.5.0" },
      worker: { ok: true, updated_at: "2026-07-12T00:00:00+00:00" },
    });

    expect(items.every((item) => item.ok)).toBe(true);
    expect(items.map((item) => item.name)).toEqual([
      "Web",
      "API",
      "Database",
      "PostGIS",
      "Worker",
    ]);
  });

  it("keeps the web check healthy when the API status is unavailable", () => {
    const items = buildStatusItems(null);

    expect(items[0]).toMatchObject({ name: "Web", ok: true });
    expect(items.slice(1).every((item) => item.ok)).toBe(false);
  });
});
