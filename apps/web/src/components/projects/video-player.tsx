"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";

export interface VideoPlayerHandle {
  seek: (seconds: number) => void;
}

export interface VideoPlayerProps {
  src: string;
  title: string;
  onTime: (seconds: number) => void;
  onError: () => void;
}

/** Native player that reports the playhead every animation frame while playing. */
export const VideoPlayer = forwardRef<VideoPlayerHandle, VideoPlayerProps>(function VideoPlayer(
  { src, title, onTime, onError },
  ref,
) {
  const video = useRef<HTMLVideoElement>(null);
  const frame = useRef<number | null>(null);

  useImperativeHandle(ref, () => ({
    seek(seconds: number): void {
      const el = video.current;
      if (el === null) return;
      el.currentTime = Math.max(0, seconds);
      onTime(el.currentTime);
    },
  }));

  useEffect(() => {
    const el = video.current;
    if (el === null) return undefined;
    const tick = (): void => {
      onTime(el.currentTime);
      frame.current = el.paused ? null : requestAnimationFrame(tick);
    };
    const start = (): void => {
      if (frame.current === null) frame.current = requestAnimationFrame(tick);
    };
    const report = (): void => onTime(el.currentTime);
    el.addEventListener("play", start);
    el.addEventListener("seeked", report);
    el.addEventListener("pause", report);
    return () => {
      el.removeEventListener("play", start);
      el.removeEventListener("seeked", report);
      el.removeEventListener("pause", report);
      if (frame.current !== null) cancelAnimationFrame(frame.current);
      frame.current = null;
    };
  }, [onTime]);

  return (
    <video
      ref={video}
      src={src}
      controls
      playsInline
      preload="metadata"
      onError={onError}
      aria-label={`Video: ${title}`}
      className="aspect-video w-full rounded-lg bg-black"
    />
  );
});
