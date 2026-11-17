"use client";

import type { TranscriptOut } from "@clipforge/shared-types";
import { memo, useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import { activeWordIndex, formatTimestamp } from "@/lib/transcript";
import { cn } from "@/lib/utils";

export interface TranscriptPanelProps {
  transcript: TranscriptOut;
  currentTime: number;
  onSeek: (seconds: number) => void;
}

interface SegmentProps {
  transcript: TranscriptOut;
  segmentIndex: number;
  activeWord: number;
  focusWord: number;
  onSeek: (seconds: number) => void;
  onFocusWord: (index: number) => void;
}

const Segment = memo(function Segment({
  transcript,
  segmentIndex,
  activeWord,
  focusWord,
  onSeek,
  onFocusWord,
}: SegmentProps) {
  const segment = transcript.segments[segmentIndex];
  if (segment === undefined) return null;
  const words = transcript.words.slice(segment.first_word, segment.first_word + segment.word_count);
  return (
    <div className="flex gap-3 py-1.5 [contain-intrinsic-size:auto_3rem] [content-visibility:auto]">
      <button
        type="button"
        onClick={() => onSeek(segment.start)}
        className="text-muted-foreground hover:text-foreground focus-visible:ring-ring mt-0.5 h-fit shrink-0 rounded px-1 font-mono text-xs tabular-nums focus-visible:outline-none focus-visible:ring-2"
        aria-label={`Play from ${formatTimestamp(segment.start)}`}
      >
        {formatTimestamp(segment.start)}
      </button>
      <p className="leading-7">
        {words.map((word, i) => {
          const index = segment.first_word + i;
          const active = index === activeWord;
          return (
            <button
              key={index}
              type="button"
              data-word={index}
              tabIndex={index === focusWord ? 0 : -1}
              aria-current={active ? "true" : undefined}
              onClick={() => onSeek(word.start)}
              onFocus={() => onFocusWord(index)}
              title={formatTimestamp(word.start)}
              className={cn(
                "hover:bg-accent focus-visible:ring-ring rounded-sm px-px transition-colors focus-visible:outline-none focus-visible:ring-2",
                active && "bg-yellow-300 text-black hover:bg-yellow-300",
                word.conf < 0.5 && !active && "text-muted-foreground",
              )}
            >
              {word.w}
            </button>
          );
        })}
      </p>
    </div>
  );
});

export function TranscriptPanel({ transcript, currentTime, onSeek }: TranscriptPanelProps) {
  const headingId = useId();
  const scroller = useRef<HTMLDivElement>(null);
  const [follow, setFollow] = useState(true);
  const [focusWord, setFocusWord] = useState(0);
  const activeWord = activeWordIndex(transcript.words, currentTime);
  const lastWord = transcript.words.length - 1;

  useEffect(() => {
    if (!follow || activeWord < 0) return;
    const el = scroller.current?.querySelector<HTMLElement>(`[data-word="${activeWord}"]`);
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeWord, follow]);

  const moveFocus = useCallback(
    (index: number): void => {
      const clamped = Math.max(0, Math.min(lastWord, index));
      setFocusWord(clamped);
      scroller.current?.querySelector<HTMLElement>(`[data-word="${clamped}"]`)?.focus();
    },
    [lastWord],
  );

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    const target = event.target as HTMLElement;
    if (target.dataset.word === undefined) return;
    const keys: Record<string, number> = {
      ArrowRight: focusWord + 1,
      ArrowLeft: focusWord - 1,
      ArrowDown: focusWord + 10,
      ArrowUp: focusWord - 10,
      Home: 0,
      End: lastWord,
    };
    const next = keys[event.key];
    if (next !== undefined) {
      event.preventDefault();
      moveFocus(next);
    }
  }

  return (
    <section aria-labelledby={headingId} className="flex min-h-0 flex-col">
      <div className="flex items-center justify-between gap-3 border-b pb-2">
        <h2 id={headingId} className="font-medium">
          Transcript
          <span className="text-muted-foreground ml-2 text-xs font-normal uppercase">
            {transcript.language}
          </span>
        </h2>
        <label className="text-muted-foreground flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={follow}
            onChange={(e) => setFollow(e.target.checked)}
            className="size-3.5 accent-current"
          />
          Follow playback
        </label>
      </div>
      <p className="sr-only">
        Select a word to jump the video to it. Use the arrow keys to move between words.
      </p>
      {transcript.words.length === 0 ? (
        <p className="text-muted-foreground py-6 text-sm">No speech was transcribed.</p>
      ) : (
        <div
          ref={scroller}
          onKeyDown={onKeyDown}
          className="min-h-0 flex-1 overflow-y-auto py-2 pr-2 text-sm"
        >
          {transcript.segments.map((segment, i) => (
            <Segment
              key={`${segment.start}-${segment.first_word}`}
              transcript={transcript}
              segmentIndex={i}
              activeWord={
                activeWord >= segment.first_word &&
                activeWord < segment.first_word + segment.word_count
                  ? activeWord
                  : -1
              }
              focusWord={
                focusWord >= segment.first_word &&
                focusWord < segment.first_word + segment.word_count
                  ? focusWord
                  : -1
              }
              onSeek={onSeek}
              onFocusWord={setFocusWord}
            />
          ))}
        </div>
      )}
    </section>
  );
}
