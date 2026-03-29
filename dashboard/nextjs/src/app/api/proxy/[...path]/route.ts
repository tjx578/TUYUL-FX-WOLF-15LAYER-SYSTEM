import { NextRequest, NextResponse } from "next/server";

/**
 * Single canonical backend proxy — runtime route handler.
 *
 * ALL browser REST traffic flows through this handler.  There are no
 * build-time rewrites; getRestPrefix() always returns "/api/proxy" on the
 * client, so every fetch request arrives here as:
 *
 *   /api/proxy/api/v1/<resource>
 *
 * The handler reads INTERNAL_API_URL at request time (not build time),
 * strips the /api/proxy prefix that Next.js already consumed, and
 * forwards the remaining path to the backend.
 *
 * Traceability headers on every response:
 *   x-proxy-target  — resolved backend origin (no credentials/path)
 *   x-proxy-status  — "ok" | "misconfigured" | "error"
 */

/** Resolved backend origin or null when not configured. */
function getBackendUrl(): string | null {
  const url =
    process.env.INTERNAL_API_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "";

  if (!url) {
    if (process.env.NODE_ENV === "development") {
      return "http://localhost:8000";
    }
    return null;
  }

  // Normalize: strip trailing slash and accidental /api suffix
  return url.replace(/\/+$/, "").replace(/\/api$/, "");
}

async function proxyRequest(
  request: NextRequest,
  path: string[]
): Promise<NextResponse> {
  const backendUrl = getBackendUrl();

  // Fail-fast: no backend URL configured outside of local dev
  if (!backendUrl) {
    console.error(
      "[api/proxy] PROXY_MISCONFIGURED: INTERNAL_API_URL / NEXT_PUBLIC_API_BASE_URL not set."
    );
    return NextResponse.json(
      {
        error: "Proxy misconfigured — backend URL not set",
        code: "PROXY_MISCONFIGURED",
        detail:
          "Set INTERNAL_API_URL (server-side) or NEXT_PUBLIC_API_BASE_URL to the Railway backend origin.",
      },
      {
        status: 503,
        headers: {
          "x-proxy-target": "unresolved",
          "x-proxy-status": "misconfigured",
        },
      }
    );
  }

  const joinedPath = path.join("/");

  // Canonical path mapping.
  //
  // getRestPrefix() returns "/api/proxy" on the client, so callers
  // always produce:  /api/proxy/api/v1/<resource>
  //
  // Next.js strips the /api/proxy prefix and hands us the rest,
  // e.g. ["api", "v1", "trades", "active"] → joinedPath = "api/v1/trades/active".
  //
  // We prepend "/" to reconstruct the backend path.  Special health
  // endpoints are mapped explicitly to their root-level paths.
  let targetPath: string;
  if (joinedPath === "health" || joinedPath === "api/health" || joinedPath === "api/v1/health") {
    targetPath = "/health";
  } else if (joinedPath === "healthz" || joinedPath === "api/healthz") {
    targetPath = "/healthz";
  } else if (joinedPath === "readyz" || joinedPath === "api/readyz") {
    targetPath = "/readyz";
  } else if (joinedPath.startsWith("api/")) {
    // Canonical form: path already includes /api/ prefix → use as-is.
    targetPath = `/${joinedPath}`;
  } else {
    // Fallback for any non-canonical caller — prepend /api/.
    targetPath = `/api/${joinedPath}`;
  }
  const targetUrl = new URL(targetPath, backendUrl);

  // Forward query params
  request.nextUrl.searchParams.forEach((value, key) => {
    targetUrl.searchParams.set(key, value);
  });

  // Build headers, forwarding most but not host
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    // Skip headers that shouldn't be forwarded
    if (
      !["host", "connection", "keep-alive", "transfer-encoding"].includes(
        key.toLowerCase()
      )
    ) {
      headers.set(key, value);
    }
  });

  // Auth comes from the session cookie injected by middleware, or from
  // the client's own Authorization header.  No API_KEY fallback.

  // Safe target label for headers (origin only, no credentials/path)
  const targetLabel = `${targetUrl.protocol}//${targetUrl.host}`;

  try {
    const response = await fetch(targetUrl.toString(), {
      method: request.method,
      headers,
      body:
        request.method !== "GET" && request.method !== "HEAD"
          ? await request.text()
          : undefined,
      // @ts-expect-error - duplex is needed for streaming but not in types
      duplex: "half",
    });

    // Build response headers
    const responseHeaders = new Headers();
    response.headers.forEach((value, key) => {
      // Skip hop-by-hop headers
      if (
        !["transfer-encoding", "connection", "keep-alive"].includes(
          key.toLowerCase()
        )
      ) {
        responseHeaders.set(key, value);
      }
    });

    // Traceability headers
    responseHeaders.set("x-proxy-target", targetLabel);
    responseHeaders.set("x-proxy-status", "ok");

    return new NextResponse(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    console.error(`[api/proxy] Failed to proxy ${targetUrl}:`, error);
    return NextResponse.json(
      {
        error: "Backend unavailable",
        detail:
          error instanceof Error ? error.message : "Connection failed",
        target: targetLabel,
      },
      {
        status: 502,
        headers: {
          "x-proxy-target": targetLabel,
          "x-proxy-status": "error",
        },
      }
    );
  }
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyRequest(request, path);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyRequest(request, path);
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyRequest(request, path);
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyRequest(request, path);
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyRequest(request, path);
}
