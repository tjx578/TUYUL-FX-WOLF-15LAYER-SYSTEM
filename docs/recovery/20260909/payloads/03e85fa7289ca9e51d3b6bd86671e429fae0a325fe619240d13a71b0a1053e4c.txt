/** Explicit Phase-1 dashboard proxy boundary. */
export const READ_ONLY_PATHS: readonly string[] = Object.freeze([
  "health",
  "healthz",
  "readyz",
  "api/health",
  "api/healthz",
  "api/readyz",
  "api/v1/status",
  "api/v1/accounts",
  "api/v1/risk",
  "api/v1/verdict",
  "api/v1/trades",
  "api/v1/journal",
  "api/v1/calendar",
  "api/v1/context",
  "api/v1/pipeline",
  "api/v1/l12",
  "api/v1/prices",
  "api/v1/pairs",
  "api/v1/probability",
  "api/v1/prop-firm",
  "api/v1/authority/surface",
  "api/v1/audit",
  "dashboard",
  "bff",
]);

export function isAllowlistedReadPath(path: string): boolean {
  return READ_ONLY_PATHS.some(
    (allowed) => path === allowed || path.startsWith(`${allowed}/`),
  );
}
