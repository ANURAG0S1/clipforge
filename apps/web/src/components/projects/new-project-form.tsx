"use client";

import type { ProjectOut } from "@clipforge/shared-types";
import { useQueryClient } from "@tanstack/react-query";
import { FileVideo, Link2, Loader2, Upload, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState, type DragEvent, type FormEvent } from "react";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError } from "@/lib/api";
import {
  createProject,
  formatBytes,
  presignUpload,
  projectKeys,
  titleFromFilename,
  UploadAbortedError,
  uploadToPresignedUrl,
} from "@/lib/projects";
import { cn } from "@/lib/utils";
import { videoContentType } from "@/lib/video-file";

type UploadPhase =
  | { kind: "idle" }
  | { kind: "uploading"; loaded: number; total: number }
  | { kind: "creating" };

const urlSchema = z
  .string()
  .trim()
  .min(1, "Paste a video link")
  .url("Enter a full link starting with https://")
  .refine((v) => /^https?:\/\//i.test(v), "Only http(s) links are supported");

const titleSchema = z
  .string()
  .trim()
  .min(1, "Give your project a title")
  .max(200, "Title is too long");

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 413) return error.detail;
    if (error.status === 422) return error.detail;
    if (error.status === 429) return "You've created a lot of projects recently. Try again later.";
    if (error.status === 0) return error.detail;
    return error.detail || "Something went wrong.";
  }
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

export function NewProjectForm() {
  const id = useId();
  const router = useRouter();
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [phase, setPhase] = useState<UploadPhase>({ kind: "idle" });
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const busy = phase.kind !== "idle";

  useEffect(() => () => abortRef.current?.abort(), []);

  function finish(project: ProjectOut): void {
    queryClient.setQueryData<ProjectOut[]>(projectKeys.all, (old) => [project, ...(old ?? [])]);
    void queryClient.invalidateQueries({ queryKey: projectKeys.all });
    router.push("/");
  }

  function pickFile(candidate: File | undefined): void {
    setError(null);
    if (candidate === undefined) return;
    if (videoContentType(candidate) === null) {
      setError(`"${candidate.name}" isn't a video file.`);
      return;
    }
    setFile(candidate);
    if (title.trim() === "") setTitle(titleFromFilename(candidate.name));
  }

  function onDrop(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    setDragging(false);
    if (!busy) pickFile(event.dataTransfer.files[0]);
  }

  async function submitUpload(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (busy) return;
    if (file === null) {
      setError("Choose a video to upload");
      return;
    }
    const parsedTitle = titleSchema.safeParse(title);
    if (!parsedTitle.success) {
      setError(parsedTitle.error.issues[0]?.message ?? "Invalid title");
      return;
    }
    const contentType = videoContentType(file);
    if (contentType === null) {
      setError("That file isn't a video.");
      return;
    }
    const controller = new AbortController();
    abortRef.current = controller;
    setError(null);
    setPhase({ kind: "uploading", loaded: 0, total: file.size });
    try {
      const typed =
        file.type === contentType ? file : new File([file], file.name, { type: contentType });
      const presigned = await presignUpload(typed);
      await uploadToPresignedUrl(
        presigned.upload_url,
        typed,
        presigned.content_type,
        (p) => setPhase({ kind: "uploading", loaded: p.loaded, total: p.total }),
        controller.signal,
      );
      setPhase({ kind: "creating" });
      finish(
        await createProject({
          title: parsedTitle.data,
          source: { type: "upload", key: presigned.key },
        }),
      );
    } catch (err: unknown) {
      setPhase({ kind: "idle" });
      if (!(err instanceof UploadAbortedError)) setError(errorMessage(err));
    } finally {
      abortRef.current = null;
    }
  }

  async function submitUrl(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (busy) return;
    const parsedUrl = urlSchema.safeParse(url);
    if (!parsedUrl.success) {
      setError(parsedUrl.error.issues[0]?.message ?? "Invalid link");
      return;
    }
    const parsedTitle = titleSchema.safeParse(title === "" ? parsedUrl.data : title);
    if (!parsedTitle.success) {
      setError(parsedTitle.error.issues[0]?.message ?? "Invalid title");
      return;
    }
    setError(null);
    setPhase({ kind: "creating" });
    try {
      finish(
        await createProject({
          title: parsedTitle.data.slice(0, 200),
          source: { type: "url", url: parsedUrl.data },
        }),
      );
    } catch (err: unknown) {
      setPhase({ kind: "idle" });
      setError(errorMessage(err));
    }
  }

  const errorBox =
    error !== null ? (
      <p
        role="alert"
        className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-3 py-2 text-sm"
      >
        {error}
      </p>
    ) : null;

  const titleField = (
    <div className="grid gap-2">
      <Label htmlFor={`${id}-title`}>Title</Label>
      <Input
        id={`${id}-title`}
        value={title}
        maxLength={200}
        onChange={(e) => setTitle(e.target.value)}
        disabled={busy}
        placeholder="e.g. Podcast episode 42"
      />
    </div>
  );

  return (
    <Tabs
      defaultValue="upload"
      onValueChange={() => {
        if (!busy) setError(null);
      }}
    >
      <TabsList className="w-full sm:w-auto">
        <TabsTrigger value="upload" className="flex-1 sm:flex-none" disabled={busy}>
          <Upload aria-hidden="true" className="mr-1.5 size-4" />
          Upload a file
        </TabsTrigger>
        <TabsTrigger value="url" className="flex-1 sm:flex-none" disabled={busy}>
          <Link2 aria-hidden="true" className="mr-1.5 size-4" />
          Paste a link
        </TabsTrigger>
      </TabsList>

      <TabsContent value="upload">
        <form noValidate onSubmit={(e) => void submitUpload(e)} className="grid gap-4">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              if (!busy) setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={cn(
              "flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-8 text-center transition-colors",
              dragging ? "border-primary bg-accent" : "border-input",
            )}
          >
            {file === null ? (
              <>
                <Upload aria-hidden="true" className="text-muted-foreground size-8" />
                <p className="text-muted-foreground text-sm">Drag and drop a video here, or</p>
              </>
            ) : (
              <p className="flex items-center gap-2 text-sm">
                <FileVideo aria-hidden="true" className="size-5 shrink-0" />
                <span className="break-all font-medium">{file.name}</span>
                <span className="text-muted-foreground">({formatBytes(file.size)})</span>
              </p>
            )}
            <input
              ref={fileInput}
              type="file"
              accept="video/*,.mkv,.ts"
              className="sr-only"
              tabIndex={-1}
              aria-hidden="true"
              onChange={(e) => {
                pickFile(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => fileInput.current?.click()}
            >
              {file === null ? "Choose a file" : "Choose a different file"}
            </Button>
          </div>

          {titleField}
          {errorBox}

          {phase.kind === "uploading" && (
            <div className="grid gap-2" aria-live="polite">
              <Progress
                value={phase.total > 0 ? (phase.loaded / phase.total) * 100 : 0}
                aria-label="Upload progress"
              />
              <p className="text-muted-foreground text-xs">
                Uploading {formatBytes(phase.loaded)} of {formatBytes(phase.total)}
              </p>
            </div>
          )}

          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            {phase.kind === "uploading" && (
              <Button type="button" variant="outline" onClick={() => abortRef.current?.abort()}>
                <X aria-hidden="true" />
                Cancel upload
              </Button>
            )}
            <Button type="submit" disabled={busy || file === null}>
              {busy && <Loader2 aria-hidden="true" className="animate-spin" />}
              {phase.kind === "creating" ? "Creating project…" : "Upload and create project"}
            </Button>
          </div>
        </form>
      </TabsContent>

      <TabsContent value="url">
        <form noValidate onSubmit={(e) => void submitUrl(e)} className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor={`${id}-url`}>Video link</Label>
            <Input
              id={`${id}-url`}
              type="url"
              inputMode="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              disabled={busy}
              placeholder="https://www.youtube.com/watch?v=…"
            />
            <p className="text-muted-foreground text-xs">
              YouTube and most public video pages work. Up to 1080p is imported.
            </p>
          </div>
          {titleField}
          {errorBox}
          <div className="flex justify-end">
            <Button type="submit" disabled={busy}>
              {busy && <Loader2 aria-hidden="true" className="animate-spin" />}
              {busy ? "Creating project…" : "Import and create project"}
            </Button>
          </div>
        </form>
      </TabsContent>
    </Tabs>
  );
}
