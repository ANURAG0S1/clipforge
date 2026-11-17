import type { TranscriptOut } from "@clipforge/shared-types";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TranscriptPanel } from "./transcript-panel";

const transcript: TranscriptOut = {
  language: "en",
  duration_s: 10,
  words: [
    { w: " Welcome", start: 0.5, end: 1.0, conf: 0.9 },
    { w: " to", start: 1.0, end: 1.2, conf: 0.9 },
    { w: " ClipForge.", start: 1.2, end: 2.0, conf: 0.4 },
    { w: " Next", start: 6.0, end: 6.4, conf: 0.9 },
  ],
  segments: [
    { start: 0.5, end: 2.0, text: "Welcome to ClipForge.", first_word: 0, word_count: 3 },
    { start: 6.0, end: 6.4, text: "Next", first_word: 3, word_count: 1 },
  ],
};

describe("TranscriptPanel", () => {
  it("seeks to a word's start when it is clicked", async () => {
    const onSeek = vi.fn();
    render(<TranscriptPanel transcript={transcript} currentTime={0} onSeek={onSeek} />);
    await userEvent.click(screen.getByRole("button", { name: "ClipForge." }));
    expect(onSeek).toHaveBeenCalledWith(1.2);
    await userEvent.click(screen.getByRole("button", { name: "Play from 0:06" }));
    expect(onSeek).toHaveBeenLastCalledWith(6.0);
  });

  it("highlights the word at the playhead", () => {
    render(<TranscriptPanel transcript={transcript} currentTime={1.1} onSeek={vi.fn()} />);
    expect(screen.getByRole("button", { name: "to" })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: "Welcome" })).not.toHaveAttribute("aria-current");
  });

  it("is keyboard navigable with a single tab stop for words", async () => {
    const onSeek = vi.fn();
    render(<TranscriptPanel transcript={transcript} currentTime={0} onSeek={onSeek} />);
    const words = ["Welcome", "to", "ClipForge.", "Next"].map((n) =>
      screen.getByRole("button", { name: n }),
    );
    expect(words.filter((w) => w.tabIndex === 0)).toHaveLength(1);

    words[0]?.focus();
    await userEvent.keyboard("{ArrowRight}{ArrowRight}");
    expect(words[2]).toHaveFocus();
    await userEvent.keyboard("{End}");
    expect(words[3]).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(onSeek).toHaveBeenCalledWith(6.0);
  });

  it("shows an empty state when nothing was transcribed", () => {
    render(
      <TranscriptPanel
        transcript={{ ...transcript, words: [], segments: [] }}
        currentTime={0}
        onSeek={vi.fn()}
      />,
    );
    expect(screen.getByText("No speech was transcribed.")).toBeInTheDocument();
  });
});
