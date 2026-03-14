import { headers, cookies } from "next/headers";
import { redirect } from "next/navigation";
import type { SessionUser, UserRole } from "@/contracts/auth";
import { SessionUserSchema } from "@/schema/authSchema";
import { AUTH_SESSION } from "@/lib/endpoints";

const SESSION_COOKIE = "wolf15_session_token";

function getApiBase(): string | null {
  // Check all known env var names in priority order.
  // API_BASE_URL is the primary server-side var (not exposed to browser).
  const base =
    process.env.API_BASE_URL ||
    process.env.INTERNAL_API_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!base || base.trim() === "") {
    return null;
  }
  return base.replace(/\/$/, "");
}

function toRedirectPath(): string {
  return "/login";
}

export async function getVerifiedSessionUser(): Promise<SessionUser | null> {
  // Always call headers()/cookies() so Next.js marks the route as dynamic
  // and never statically prerenders routes guarded by this function.
  const h = await headers();
  const jar = await cookies();

  const apiBase = getApiBase();
  if (!apiBase) {
    return null;
  }

  // Priority: first-party cookie set by /api/set-session → Authorization header
  // forwarded from client. The Railway HttpOnly cookie is cross-site and won't
  // be present in the browser, so we rely on our own Vercel-domain cookie.
  const sessionToken =
    jar.get(SESSION_COOKIE)?.value ||
    h.get("authorization")?.replace(/^Bearer\s+/i, "");

  if (!sessionToken) {
    return null;
  }

  try {
    const response = await fetch(`${apiBase}${AUTH_SESSION}`, {
      method: "GET",
      headers: {
        authorization: `Bearer ${sessionToken}`,
      },
      cache: "no-store",
    });

    if (!response.ok) {
      return null;
    }

    const raw = await response.json();
    return SessionUserSchema.parse(raw);
  } catch {
    return null;
  }
}

export async function requireVerifiedSession(
  allowedRoles?: readonly UserRole[]
): Promise<SessionUser> {
  const session = await getVerifiedSessionUser();

  if (!session) {
    redirect(toRedirectPath());
  }

  if (allowedRoles && !allowedRoles.includes(session.role)) {
    redirect(toRedirectPath());
  }

  return session;
}
