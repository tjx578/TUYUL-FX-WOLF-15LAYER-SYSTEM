import { NextRequest, NextResponse } from "next/server";

const SESSION_COOKIE = "wolf15_session";
const DEV_OWNER_ENABLED =
  process.env.NODE_ENV !== "production" &&
  process.env.DASHBOARD_ALLOW_DEV_OWNER === "true";

const PROXY_PREFIXES = [
  "/api/",
  "/health",
  "/auth/",
  "/preferences",
  "/pipeline",
];

const PUBLIC_PAGE_PREFIXES = ["/unauthorized"];

function isProxyRoute(pathname: string): boolean {
  return PROXY_PREFIXES.some((p) => pathname.startsWith(p));
}

function isPublicPage(pathname: string): boolean {
  return PUBLIC_PAGE_PREFIXES.some((p) => pathname.startsWith(p));
}

function handleProxyRoute(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;

  if (pathname.startsWith("/api/auth/") || pathname.startsWith("/api/set-session")) {
    return NextResponse.next();
  }

  if (request.headers.get("authorization")) {
    return NextResponse.next();
  }

  const sessionToken = request.cookies.get(SESSION_COOKIE)?.value?.trim();
  if (sessionToken) {
    const headers = new Headers(request.headers);
    headers.set("authorization", `Bearer ${sessionToken}`);
    return NextResponse.next({ request: { headers } });
  }

  const apiKey = process.env.API_KEY?.trim();
  if (apiKey) {
    const headers = new Headers(request.headers);
    headers.set("authorization", `Bearer ${apiKey}`);
    return NextResponse.next({ request: { headers } });
  }

  return NextResponse.next();
}

function handlePageRoute(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;

  if (isPublicPage(pathname) || DEV_OWNER_ENABLED) {
    return NextResponse.next();
  }

  const sessionToken = request.cookies.get(SESSION_COOKIE)?.value?.trim();
  const authHeader = request.headers.get("authorization")?.trim();

  if (sessionToken || authHeader) {
    return NextResponse.next();
  }

  const url = request.nextUrl.clone();
  url.pathname = "/unauthorized";
  url.searchParams.set("reason", "auth_required");
  return NextResponse.redirect(url);
}

export function middleware(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;

  if (isProxyRoute(pathname)) {
    return handleProxyRoute(request);
  }

  return handlePageRoute(request);
}

export const config = {
  matcher: ["/((?!login|_next/|favicon\\.ico).*)"],
};
