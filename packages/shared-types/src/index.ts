import type { components, paths } from "./schema";

export type { components, paths };

/** Shorthand for a named schema in the OpenAPI `components.schemas` section. */
export type Schema<Name extends keyof components["schemas"]> = components["schemas"][Name];

export type HealthReport = Schema<"HealthReport">;
export type CheckResult = Schema<"CheckResult">;
export type Credentials = Schema<"Credentials">;
export type UserOut = Schema<"UserOut">;
export type PresignRequest = Schema<"PresignRequest">;
export type PresignResponse = Schema<"PresignResponse">;
export type ProjectCreate = Schema<"ProjectCreate">;
export type ProjectOut = Schema<"ProjectOut">;
export type ProjectStatus = ProjectOut["status"];
export type JobOut = Schema<"JobOut">;
export type HTTPValidationError = Schema<"HTTPValidationError">;
