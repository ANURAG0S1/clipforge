import type {
  PresignResponse,
  ProjectCreate,
  ProjectOut,
  ProjectStatus,
} from "@clipforge/shared-types";

import { apiFetch } from "@/lib/api";

export const projectKeys = {
  all: ["projects"] as const,
  detail: (id: string) => ["projects", id] as const,
};

export const TERMINAL_STATUSES: ReadonlySet<ProjectStatus> = new Set(["ready", "failed"]);

export function isProcessing(project: ProjectOut): boolean {
  return !TERMINAL_STATUSES.has(project.status);
}

export async function listProjects(signal?: AbortSignal): Promise<ProjectOut[]> {
  return apiFetch<ProjectOut[]>("/projects", signal === undefined ? {} : { signal });
}

export async function createProject(body: ProjectCreate): Promise<ProjectOut> {
  return apiFetch<ProjectOut>("/projects", { method: "POST", json: body });
}

export async function deleteProject(id: string): Promise<void> {
  await apiFetch<null>(`/projects/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function presignUpload(file: File): Promise<PresignResponse> {
  return apiFetch<PresignResponse>("/uploads/presign", {
    method: "POST",
    json: { filename: file.name, content_type: file.type, size_bytes: file.size },
  });
}

export class UploadAbortedError extends Error {
  constructor() {
    super("Upload cancelled");
    this.name = "UploadAbortedError";
  }
}

export interface UploadProgress {
  loaded: number;
  total: number;
}

/**
 * PUT a file straight to object storage with a presigned URL.
 * XHR (not fetch) because fetch has no upload progress events.
 */
export function uploadToPresignedUrl(
  url: string,
  file: File,
  contentType: string,
  onProgress: (p: UploadProgress) => void,
  signal: AbortSignal,
): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(new UploadAbortedError());
      return;
    }
    const xhr = new XMLHttpRequest();
    const onAbort = (): void => xhr.abort();
    signal.addEventListener("abort", onAbort, { once: true });
    const cleanup = (): void => signal.removeEventListener("abort", onAbort);

    xhr.upload.onprogress = (event: ProgressEvent): void => {
      onProgress({ loaded: event.loaded, total: event.lengthComputable ? event.total : file.size });
    };
    xhr.onload = (): void => {
      cleanup();
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(`Upload failed (HTTP ${xhr.status})`));
    };
    xhr.onerror = (): void => {
      cleanup();
      reject(new Error("Upload failed: network error"));
    };
    xhr.onabort = (): void => {
      cleanup();
      reject(new UploadAbortedError());
    };
    xhr.open("PUT", url);
    xhr.setRequestHeader("Content-Type", contentType);
    xhr.send(file);
  });
}

export function titleFromFilename(name: string): string {
  const base = name
    .replace(/\.[^./\\]+$/, "")
    .replace(/[_-]+/g, " ")
    .trim();
  return (base.length > 0 ? base : "Untitled video").slice(0, 200);
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return "—";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(h > 0 ? 2 : 1, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"] as const;
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}
