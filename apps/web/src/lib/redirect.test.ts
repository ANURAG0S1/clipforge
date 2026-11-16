import { describe, expect, it } from "vitest";

import { safeNextPath } from "./redirect";

describe("safeNextPath", () => {
  it("keeps same-origin paths", () => {
    expect(safeNextPath("/new")).toBe("/new");
    expect(safeNextPath("/projects/1?x=2")).toBe("/projects/1?x=2");
  });

  it("rejects external and protocol-relative targets", () => {
    for (const bad of [
      "https://evil.com",
      "//evil.com",
      "/\\evil.com",
      "javascript:alert(1)",
      "",
    ]) {
      expect(safeNextPath(bad)).toBe("/");
    }
    expect(safeNextPath(null, "/x")).toBe("/x");
  });
});
