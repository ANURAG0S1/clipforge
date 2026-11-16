"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Loader2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useRef, useState } from "react";

import { STATUS_LABEL, STATUS_VARIANT } from "@/components/projects/status";
import { TranscriptPanel } from "@/components/projects/transcript-panel";
import { VideoPlayer, type VideoPlayerHandle } from "@/components/projects/video-player";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { ApiError } from "@/lib/api";
import {
  formatDuration,
  getProject,
  getProjectMedia,
  getTranscript,
  isProcessing,
  projectKeys,
} from "@/lib/projects";

const POLL_MS = 3000;

function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

export function ProjectWorkspace({ projectId }: { projectId: string }) {
  const player = useRef<VideoPlayerHandle>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [mediaRetried, setMediaRetried] = useState(false);

  const project = useQuery({
    queryKey: projectKeys.detail(projectId),
    queryFn: ({ signal }) => getProject(projectId, signal),
    refetchInterval: (query) =>
      query.state.data !== undefined && isProcessing(query.state.data) ? POLL_MS : false,
  });
  const hasVideo = project.data?.duration_s !== null && project.data?.duration_s !== undefined;
  const media = useQuery({
    queryKey: projectKeys.media(projectId),
    queryFn: ({ signal }) => getProjectMedia(projectId, signal),
    enabled: hasVideo,
    staleTime: 60 * 60 * 1000,
  });
  const transcriptReady = project.data?.status === "ready";
  const transcript = useQuery({
    queryKey: projectKeys.transcript(projectId),
    queryFn: ({ signal }) => getTranscript(projectId, signal),
    enabled: transcriptReady,
    staleTime: Infinity,
  });

  const seek = useCallback((seconds: number) => player.current?.seek(seconds), []);
  const onMediaError = useCallback(() => {
    // Presigned URLs expire; fetch a fresh one once before giving up.
    if (!mediaRetried) {
      setMediaRetried(true);
      void media.refetch();
    }
  }, [media, mediaRetried]);

  if (project.isPending) {
    return (
      <div className="flex justify-center py-20" role="status">
        <Loader2 aria-hidden="true" className="text-muted-foreground size-6 animate-spin" />
        <span className="sr-only">Loading project…</span>
      </div>
    );
  }
  if (project.isError) {
    return (
      <Card className="flex flex-col items-center gap-3 p-10 text-center">
        <p role="alert" className="text-muted-foreground text-sm">
          {isNotFound(project.error)
            ? "This project doesn't exist or was deleted."
            : "Couldn't load this project."}
        </p>
        <Button asChild variant="outline">
          <Link href="/">Back to projects</Link>
        </Button>
      </Card>
    );
  }

  const p = project.data;
  const processing = isProcessing(p);

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <Button asChild variant="ghost" size="icon" aria-label="Back to projects">
          <Link href="/">
            <ArrowLeft aria-hidden="true" />
          </Link>
        </Button>
        <h1
          className="min-w-0 flex-1 truncate text-xl font-semibold tracking-tight"
          title={p.title}
        >
          {p.title}
        </h1>
        <span className="text-muted-foreground text-sm">{formatDuration(p.duration_s)}</span>
        <Badge variant={STATUS_VARIANT[p.status]}>
          {processing && <Loader2 aria-hidden="true" className="size-3 animate-spin" />}
          {STATUS_LABEL[p.status]}
        </Badge>
      </div>

      {processing && (
        <Card className="grid gap-2 p-4" aria-live="polite">
          <p className="text-sm">
            {STATUS_LABEL[p.status]}… {p.progress}%
          </p>
          <Progress value={p.progress} aria-label={`${STATUS_LABEL[p.status]} progress`} />
        </Card>
      )}
      {p.status === "failed" && (
        <Card className="border-destructive/50 text-destructive flex items-start gap-2 p-4 text-sm">
          <AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span role="alert">{p.error ?? "Processing failed."}</span>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="lg:sticky lg:top-20 lg:self-start">
          {!hasVideo ? (
            <div className="bg-muted text-muted-foreground flex aspect-video items-center justify-center rounded-lg text-sm">
              The preview appears once the video is imported.
            </div>
          ) : media.isError ? (
            <div className="bg-muted text-muted-foreground flex aspect-video flex-col items-center justify-center gap-3 rounded-lg text-sm">
              <p role="alert">Couldn&apos;t load the video.</p>
              <Button variant="outline" size="sm" onClick={() => void media.refetch()}>
                Try again
              </Button>
            </div>
          ) : media.data === undefined ? (
            <div className="bg-muted aspect-video animate-pulse rounded-lg" />
          ) : (
            <VideoPlayer
              ref={player}
              src={media.data.proxy_url}
              title={p.title}
              onTime={setCurrentTime}
              onError={onMediaError}
            />
          )}
        </div>

        <Card className="flex max-h-[70dvh] min-h-64 flex-col p-4 lg:max-h-[calc(100dvh-8rem)]">
          {!transcriptReady ? (
            <p className="text-muted-foreground py-6 text-sm">
              {p.status === "failed"
                ? "No transcript is available."
                : "The transcript will appear here when transcription finishes."}
            </p>
          ) : transcript.isPending ? (
            <div className="grid gap-2" aria-busy="true" aria-label="Loading transcript">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="bg-muted h-5 animate-pulse rounded" />
              ))}
            </div>
          ) : transcript.isError ? (
            <div className="text-muted-foreground grid justify-items-start gap-3 py-6 text-sm">
              <p role="alert">
                {isNotFound(transcript.error)
                  ? "This project has no transcript."
                  : "Couldn't load the transcript."}
              </p>
              {!isNotFound(transcript.error) && (
                <Button variant="outline" size="sm" onClick={() => void transcript.refetch()}>
                  Try again
                </Button>
              )}
            </div>
          ) : (
            <TranscriptPanel transcript={transcript.data} currentTime={currentTime} onSeek={seek} />
          )}
        </Card>
      </div>
    </div>
  );
}
