import { describe, expect, it } from "vitest";

import { formatBytes, formatDuration, titleFromFilename } from "./projects";
import { videoContentType } from "./video-file";

describe("videoContentType", () => {
  it("accepts browser-reported video types", () => {
    expect(videoContentType({ name: "a.mp4", type: "video/mp4" })).toBe("video/mp4");
  });
  it("infers from extension when the browser reports nothing", () => {
    expect(videoContentType({ name: "a.MKV", type: "" })).toBe("video/x-matroska");
    expect(videoContentType({ name: "a.ts", type: "application/octet-stream" })).toBe("video/mp2t");
  });
  it("rejects non-video files", () => {
    expect(videoContentType({ name: "a.png", type: "image/png" })).toBeNull();
    expect(videoContentType({ name: "a.mp4", type: "text/plain" })).toBeNull();
    expect(videoContentType({ name: "notes", type: "" })).toBeNull();
  });
});

describe("formatting helpers", () => {
  it("formats durations", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(5)).toBe("0:05");
    expect(formatDuration(301.4)).toBe("5:01");
    expect(formatDuration(3725)).toBe("1:02:05");
  });
  it("formats bytes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(4 * 1024 ** 3)).toBe("4.0 GB");
  });
  it("derives titles from filenames", () => {
    expect(titleFromFilename("my_great-talk.final.mp4")).toBe("my great talk.final");
    expect(titleFromFilename(".mp4")).toBe("Untitled video");
  });
});
