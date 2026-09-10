import { cookies } from "next/headers";
import type { SessionUser, UserRole } from "@/contracts/auth";
import { hasRole } from "@/lib/auth";
import { getCoreApiUrl } from "@/lib/server/dashboardTopology";

/**
 * Owner-only auth model — explicit mode.
 *
 * DASHBOARD_MODE must be "owner" (the only supported mode).
 * This dashboard is a private owner control surface — NOT a public
 * multi-user product.  There is no login UI, no public-user session,
 * and no browser-facing API key flow.
 *
 * The mode is validated at first use.  If the env var is missing or
 * set to an unsupported value, the guard throws immediately — no
 * implicit bypass, no silent fallback.
 *
 * See docs/architecture/dashboard-control-surface.md — Auth Model.
 */

const SESSION_COOKIE = "wolf15_session";
const USER_ROLES: readonly UserRole[] = ["owner", "viewer", "operator", "risk_admin", "config_admin", "approver"];

export class SessionAuthorizationError extends Error {
  constructor(message: string, readonly status: 401 | 403 = 401) {
    super(message);
    this.name = "SessionAuthorizationError";
  }
}

function isSessionUser(value: unknown): value is SessionUser {
  if (!value || typeof value !== "object") return false;
  const user = value as Record<string, unknown>;
  return typeof user.user_id === "string" && user.user_id.length > 0 &&
    typeof user.email === "string" && typeof user.role === "string" &&
    USER_ROLES.includes(user.role as UserRole) &&
    (user.name === undefined || user.name === null || typeof user.name === "string");
}

export async function validateSessionToken(token: string): Promise<SessionUser | null> {
  const candidate = token.trim();
  if (!candidate || candidate.split(".").length !== 3) return null;
  const coreApiUrl = getCoreApiUrl();
  if (!coreApiUrl) return null;
  try {
    const response = await fetch(`${coreApiUrl}/api/auth/session`, {
      method: "GET",
      headers: { authorization: `Bearer ${candidate}`, accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) return null;
    const user: unknown = await response.json();
    return isSessionUser(user) ? user : null;
  } catch {
    return null;
  }
}

export async function getVerifiedSessionUser(): Promise<SessionUser | null> {
  const cookieStore = await cookies();
  return validateSessionToken(cookieStore.get(SESSION_COOKIE)?.value ?? "");
}

export async function requireVerifiedSession(
  allowedRoles?: readonly UserRole[],
): Promise<SessionUser> {
  const user = await getVerifiedSessionUser();
  if (!user) throw new SessionAuthorizationError("Unauthorized: validated session required");
  if (allowedRoles?.length && !hasRole(user.role, allowedRoles)) {
    throw new SessionAuthorizationError("Forbidden: role is not allowed for this route", 403);
  }
  return user;
}
