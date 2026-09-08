export const VIEWER_ROLE = "viewer" as const;
export const DASHBOARD_READ_SCOPE = "read:dashboard" as const;

export const VIEWER_ENDPOINTS = Object.freeze([
  {
    path: "dashboard/overview",
    label: "System overview",
    description: "Core status and liveness composed by the dashboard BFF.",
  },
  {
    path: "dashboard/feed-status",
    label: "Feed status",
    description: "Current market-data feed state reported by the dashboard BFF.",
  },
  {
    path: "bff/aggregated-status",
    label: "Aggregated status",
    description: "Read-only operator status with BFF provenance.",
  },
] as const);

export const VIEWER_PROXY_PATHS: readonly string[] = Object.freeze(
  VIEWER_ENDPOINTS.map((endpoint) => endpoint.path),
);

export interface AuthorizedViewerSession {
  user_id: string;
  email: string;
  role: typeof VIEWER_ROLE;
  name?: string | null;
  scopes: string[];
  auth_method: "jwt";
}

export function isAuthorizedViewerSession(
  value: unknown,
): value is AuthorizedViewerSession {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;

  const session = value as Record<string, unknown>;
  return (
    typeof session.user_id === "string" &&
    session.user_id.length > 0 &&
    typeof session.email === "string" &&
    session.email.length > 0 &&
    session.role === VIEWER_ROLE &&
    session.auth_method === "jwt" &&
    Array.isArray(session.scopes) &&
    session.scopes.every((scope) => typeof scope === "string") &&
    session.scopes.includes(DASHBOARD_READ_SCOPE) &&
    (session.name === undefined ||
      session.name === null ||
      typeof session.name === "string")
  );
}
