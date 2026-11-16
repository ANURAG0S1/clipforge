import { env } from "@/env";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(`API ${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

const detailSchemaKeys = ["detail", "message"] as const;

function extractDetail(body: unknown, fallback: string): string {
  if (typeof body === "object" && body !== null) {
    for (const key of detailSchemaKeys) {
      const value: unknown = (body as Record<string, unknown>)[key];
      if (typeof value === "string" && value.length > 0) return value;
    }
  }
  return fallback;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  json?: unknown;
  signal?: AbortSignal;
}

/**
 * Fetch a JSON endpoint on the API with the auth cookie attached.
 * Response types come from `@clipforge/shared-types`; callers pass the generated type as `T`.
 */
export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", json, signal } = options;
  const init: RequestInit = {
    method,
    credentials: "include",
    headers: json === undefined ? {} : { "Content-Type": "application/json" },
  };
  if (json !== undefined) init.body = JSON.stringify(json);
  if (signal !== undefined) init.signal = signal;

  let response: Response;
  try {
    response = await fetch(`${env.NEXT_PUBLIC_API_URL}${path}`, init);
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError(0, "Could not reach the server. Check your connection and try again.");
  }

  const text = await response.text();
  let body: unknown = null;
  if (text.length > 0) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }

  if (!response.ok) {
    throw new ApiError(
      response.status,
      extractDetail(body, response.statusText || "Request failed"),
    );
  }
  return body as T;
}
