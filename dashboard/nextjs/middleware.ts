import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

const ADMIN_PATH_PREFIX = "/audit";
const ADMIN_ROLES = new Set([
  "risk_admin",
  "config_admin",
  "approver",
]);

export function middleware(request: NextRequest) {
  if (!request.nextUrl.pathname.startsWith(ADMIN_PATH_PREFIX)) {
    return NextResponse.next();
  }

  // Coarse pre-screening only. Authoritative check is server-side in requireVerifiedSession().
  const role = request.headers.get("x-user-role");
  if (!role || !ADMIN_ROLES.has(role)) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/audit/:path*"],
};
