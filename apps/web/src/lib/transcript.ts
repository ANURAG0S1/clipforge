import type { TranscriptWord } from "@clipforge/shared-types";

/**
 * Index of the word being spoken at time ``t`` (the last word that started at or before t),
 * or -1 before the first word. Binary search: transcripts can hold tens of thousands of words.
 */
export function activeWordIndex(words: readonly TranscriptWord[], t: number): number {
  let lo = 0;
  let hi = words.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const word = words[mid];
    if (word === undefined) break;
    if (word.start <= t) {
      found = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  if (found === -1) return -1;
  const current = words[found];
  // In a pause longer than a second after the word ends, nothing is highlighted.
  return current !== undefined && t <= current.end + 1 ? found : -1;
}

export function formatTimestamp(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}
