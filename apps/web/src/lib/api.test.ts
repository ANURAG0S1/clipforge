import { describe, expect, it } from "vitest";

import { extractDetail } from "./api";

describe("extractDetail", () => {
  it("reads string details", () => {
    expect(extractDetail({ detail: "Not found" }, "x")).toBe("Not found");
  });
  it("reads the first FastAPI validation message", () => {
    const body = { detail: [{ loc: ["body", "content_type"], msg: "Value error, must be video" }] };
    expect(extractDetail(body, "x")).toBe("must be video");
  });
  it("falls back for unknown shapes", () => {
    expect(extractDetail(null, "fallback")).toBe("fallback");
    expect(extractDetail({ detail: 3 }, "fallback")).toBe("fallback");
    expect(extractDetail({ detail: [] }, "fallback")).toBe("fallback");
  });
});
