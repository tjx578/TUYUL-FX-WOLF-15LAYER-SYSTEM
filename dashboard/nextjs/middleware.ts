import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

const ADMIN_PATH_PREFIX = "/audit";
const ADMIN_ROLES = new Set(["risk_admin", "config_admin", "approver"]);
const LOGIN_PATH = "/login";
const SESSION_COOKIE = "wolf15_session";

/**
 * Paths that never trigger auth redirects.
 * Static assets and API routes are excluded via the matcher below;
 * this set catches remaining public pages.
 */
const PUBLIC_PATHS = new Set([LOGIN_PATH]);

function isPublicPath(pathname: string): boolean {
  if (PUBLIC_PATHS.has(pathname)) return true;
  for (const p of PUBLIC_PATHS) {
    if (pathname.startsWith(`${p}/`)) return true;
  }
  return false;
}

function redirectToLogin(request: NextRequest): NextResponse {
  const loginUrl = new URL(LOGIN_PATH, request.url);
  loginUrl.searchParams.set("callbackUrl", request.nextUrl.pathname);
  return NextResponse.redirect(loginUrl);
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // ── Anti-loop: never redirect public pages (especially /login) ──
  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  // ── General auth: session cookie must be present ──
  const sessionCookie = request.cookies.get(SESSION_COOKIE);
  if (!sessionCookie?.value) {
    return redirectToLogin(request);
  }

  // ── Admin paths: additional role guard (coarse pre-screen) ──
  if (pathname.startsWith(ADMIN_PATH_PREFIX)) {
    const role = request.headers.get("x-user-role");
    if (!role || !ADMIN_ROLES.has(role)) {
      return redirectToLogin(request);
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Match all paths except static files, images, and favicon.
     * API routes are handled server-side (no middleware redirect).
     */
    "/((?!_next/static|_next/image|favicon\\.ico|api/).*)",
  ],
};
