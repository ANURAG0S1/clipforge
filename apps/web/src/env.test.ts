import { describe, expect, it } from "vitest";

import { parsePublicEnv } from "./env";

describe("parsePublicEnv", () => {
  it("accepts an http URL and strips trailing slashes", () => {
    expect(parsePublicEnv({ NEXT_PUBLIC_API_URL: "http://localhost:8000//" })).toEqual({
      NEXT_PUBLIC_API_URL: "http://localhost:8000",
    });
  });

  it("fails fast when the variable is missing", () => {
    expect(() => parsePublicEnv({})).toThrow(/NEXT_PUBLIC_API_URL is required/);
  });

  it("rejects non-http schemes", () => {
    expect(() => parsePublicEnv({ NEXT_PUBLIC_API_URL: "ftp://example.com" })).toThrow(
      /must be http/,
    );
  });
});
