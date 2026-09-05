import { cookies } from "next/headers";
import type { SessionUser } from "@/contracts/auth";
import { getCoreApiUrl } from "@/lib/server/dashboardTopology";
import { isAuthorizedViewerSession } from "@/lib/viewerContract";

const SESSION_COOKIE = "wolf15_session";

export class SessionAuthorizationError extends Error {
  constructor(message: string, readonly status: 401 | 403 = 401) {
    super(message);
    this.name = "SessionAuthorizationError";
  }
}

/**
 * Ask the core auth authority to validate a candidate token, then enforce the
 * narrower visual-dashboard contract locally. A 2xx response alone is not
 * sufficient: only a JWT-backed viewer carrying read:dashboard is accepted.
 */
export async function validateSessionToken(
  token: string,
): Promise<SessionUser | null> {
  const candidate = token.trim();
  if (!candidate || candidate.split(".").length !== 3) return null;

  const coreApiUrl = getCoreApiUrl();
  if (!coreApiUrl) return null;

  try {
    const response = await fetch(coreApiUrl + "/api/auth/session", {
      method: "GET",
      headers: {
        authorization: "Bearer " + candidate,
        accept: "application/json",
        cookie: "",
      },
      cache: "no-store",
    });
    if (!response.ok) return null;

    const session: unknown = await response.json();
    return isAuthorizedViewerSession(session) ? session : null;
  } catch {
    return null;
  }
}

export async function getVerifiedSessionUser(): Promise<SessionUser | null> {
  const cookieStore = await cookies();
  return validateSessionToken(cookieStore.get(SESSION_COOKIE)?.value ?? "");
}

export async function requireVerifiedSession(): Promise<SessionUser> {
  const user = await getVerifiedSessionUser();
  if (!user) {
    throw new SessionAuthorizationError(
      "Unauthorized: scoped viewer session required",
    );
  }
  return user;
}
