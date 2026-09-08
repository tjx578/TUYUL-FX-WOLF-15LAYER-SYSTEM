import { NextRequest, NextResponse } from "next/server";

const SESSION_COOKIE = "wolf15_session";
const PROXY_PREFIX = "/api/proxy/";

function resolveSessionToken(request: NextRequest): string | null {
  return request.cookies.get(SESSION_COOKIE)?.value?.trim() || null;
}

function hasJwtShape(token: string | null): token is string {
  return Boolean(token && token.split(".").length === 3);
}

function injectProxyAuth(
  request: NextRequest,
  token: string,
): NextResponse {
  const headers = new Headers(request.headers);
  headers.set("authorization", "Bearer " + token);
  headers.delete("cookie");
  return NextResponse.next({ request: { headers } });
}

function boundaryResponse(
  status: 401 | 403,
  code: "SESSION_REQUIRED" | "VIEWER_SURFACE_BOUNDARY",
): NextResponse {
  return NextResponse.json(
    {
      error: status === 401 ? "Unauthorized" : "Forbidden",
      code,
    },
    {
      status,
      headers: { "cache-control": "no-store" },
    },
  );
}

/**
 * Edge routing guard only. Cryptographic validation and the viewer role/scope
 * checks happen in the Node route/layout and again at the BFF boundary.
 */
export function middleware(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;

  if (
    pathname === "/login" ||
    (pathname === "/api/auth/owner-login" && request.method === "POST") ||
    pathname === "/api/set-session" ||
    pathname === "/healthz"
  ) {
    return NextResponse.next();
  }

  const token = resolveSessionToken(request);

  if (pathname.startsWith(PROXY_PREFIX)) {
    if (!hasJwtShape(token)) {
      return boundaryResponse(401, "SESSION_REQUIRED");
    }
    return injectProxyAuth(request, token);
  }

  if (pathname !== "/") {
    return boundaryResponse(403, "VIEWER_SURFACE_BOUNDARY");
  }

  if (!hasJwtShape(token)) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/|favicon\\.ico).*)"],
};
