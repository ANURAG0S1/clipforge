import type { UserOut } from "@clipforge/shared-types";
import { z } from "zod";

import { apiFetch } from "@/lib/api";

export const credentialsSchema = z.object({
  email: z.string().trim().min(1, "Email is required").email("Enter a valid email address"),
  password: z
    .string()
    .min(8, "Password must be at least 8 characters")
    .max(128, "Password must be at most 128 characters"),
});

export type Credentials = z.infer<typeof credentialsSchema>;

/** Logs in; the API sets an httpOnly session cookie on success. */
export async function login(credentials: Credentials): Promise<void> {
  await apiFetch<UserOut>("/auth/login", { method: "POST", json: credentials });
}

/** Creates an account and signs in (the API sets the session cookie). */
export async function register(credentials: Credentials): Promise<void> {
  await apiFetch<UserOut>("/auth/register", { method: "POST", json: credentials });
}

export async function logout(): Promise<void> {
  await apiFetch<null>("/auth/logout", { method: "POST" });
}

export async function fetchMe(signal?: AbortSignal): Promise<UserOut> {
  return apiFetch<UserOut>("/auth/me", signal === undefined ? {} : { signal });
}
