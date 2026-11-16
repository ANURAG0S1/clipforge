import type { components, paths } from "./schema";

export type { components, paths };

/** Shorthand for a named schema in the OpenAPI `components.schemas` section. */
export type Schema<Name extends keyof components["schemas"]> = components["schemas"][Name];

export type HealthReport = Schema<"HealthReport">;
export type CheckResult = Schema<"CheckResult">;
