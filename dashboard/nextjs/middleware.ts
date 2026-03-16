import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

const SESSION_COOKIE = "wolf15_session";
const ROLE_HEADER = "x-user-role";
const ADMIN_ROLES = new Set(["risk_admin", "config_admin", "approver"]);
// Paths that require an admin role (matched by prefix)
const ADMIN_PATHS = ["/audit"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Allow /login and its sub-paths through without auth check
  if (pathname.startsWith("/login")) {
    return NextResponse.next();
  }

  const sessionCookie = request.cookies.get(SESSION_COOKIE)?.value;

  // Redirect unauthenticated requests to /login
  if (!sessionCookie) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("callbackUrl", pathname);
    return NextResponse.redirect(loginUrl, 307);
  }

  // Check admin-only paths
  const isAdminPath = ADMIN_PATHS.some((p) => pathname.startsWith(p));
  if (isAdminPath) {
    const role = request.headers.get(ROLE_HEADER);
    if (!role || !ADMIN_ROLES.has(role)) {
      const loginUrl = new URL("/login", request.url);
      loginUrl.searchParams.set("callbackUrl", pathname);
      return NextResponse.redirect(loginUrl, 307);
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon\\.ico|api/).*)",
  ],
};
