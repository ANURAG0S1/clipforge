import type { TranscriptWord } from "@clipforge/shared-types";
import { describe, expect, it } from "vitest";

import { activeWordIndex, formatTimestamp } from "./transcript";

const words: TranscriptWord[] = [
  { w: " a", start: 1, end: 1.4, conf: 1 },
  { w: " b", start: 1.5, end: 2, conf: 1 },
  { w: " c", start: 5, end: 5.5, conf: 1 },
];

describe("activeWordIndex", () => {
  it("returns -1 before the first word and for empty transcripts", () => {
    expect(activeWordIndex(words, 0.5)).toBe(-1);
    expect(activeWordIndex([], 3)).toBe(-1);
  });
  it("finds the word being spoken, including tiny gaps between words", () => {
    expect(activeWordIndex(words, 1)).toBe(0);
    expect(activeWordIndex(words, 1.45)).toBe(0);
    expect(activeWordIndex(words, 1.7)).toBe(1);
    expect(activeWordIndex(words, 5.2)).toBe(2);
  });
  it("clears the highlight during long pauses", () => {
    expect(activeWordIndex(words, 3.5)).toBe(-1);
    expect(activeWordIndex(words, 99)).toBe(-1);
  });
});

describe("formatTimestamp", () => {
  it("formats minutes and hours", () => {
    expect(formatTimestamp(0)).toBe("0:00");
    expect(formatTimestamp(65.9)).toBe("1:05");
    expect(formatTimestamp(3661)).toBe("1:01:01");
  });
});
