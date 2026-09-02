import { describe, expect, it } from "vitest";
import { browserLocale, interpolateMessage, localeTag } from "../app/i18n";

describe("localization policy", () => {
  it("selects Korean when a browser preference is Korean", () => {
    expect(browserLocale(["ja", "ko-KR", "en-US"])).toBe("ko");
  });

  it("falls back to English for unsupported or absent browser preferences", () => {
    expect(browserLocale(["fr-FR", "en-US"])).toBe("en");
    expect(browserLocale(undefined)).toBe("en");
  });

  it("maps each supported UI language to its display locale", () => {
    expect(localeTag("en")).toBe("en-US");
    expect(localeTag("ko")).toBe("ko-KR");
  });

  it("interpolates UI counts without changing unknown placeholders", () => {
    expect(interpolateMessage("Uploading {count}", { count: 3 })).toBe(
      "Uploading 3",
    );
    expect(interpolateMessage("{count} {missing}", { count: 3 })).toBe(
      "3 {missing}",
    );
  });
});
