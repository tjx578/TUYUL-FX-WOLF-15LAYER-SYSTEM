import { NextRequest, NextResponse } from "next/server";

/**
 * Dynamic API proxy that reads backend URL at **runtime**, not build time.
 * This solves the issue where next.config.js rewrites use stale env vars
 * because they're evaluated once at startup.
 */

function getBackendUrl(): string {
  // Check all possible env var names (same as next.config.js)
  const url =
    process.env.INTERNAL_API_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    process.env.API_BASE_URL ||
    (process.env.API_DOMAIN ? `https://${process.env.API_DOMAIN}` : "") ||
    "";

  if (!url) {
    // In development without env vars, fallback to localhost
    if (process.env.NODE_ENV === "development") {
      return "http://localhost:8000";
    }
    throw new Error(
      "[api/proxy] Missing backend URL. Set NEXT_PUBLIC_API_BASE_URL or INTERNAL_API_URL."
    );
  }

  // Normalize: strip trailing slash and accidental /api suffix
  return url.replace(/\/+$/, "").replace(/\/api$/, "");
}

async function proxyRequest(
  request: NextRequest,
  path: string[]
): Promise<NextResponse> {
  const backendUrl = getBackendUrl();
  const joinedPath = path.join("/");
  
  // Handle paths that already start with 'v1/' (e.g., /api/proxy/v1/health)
  // These should map to /api/v1/... on backend, not /api/v1/v1/...
  // Also handle bare 'health' endpoint
  let targetPath: string;
  if (joinedPath === "health" || joinedPath === "v1/health") {
    targetPath = "/health";
  } else if (joinedPath.startsWith("v1/")) {
    targetPath = `/api/${joinedPath}`;
  } else {
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

  // Add API key if available (for authenticated backend calls)
  const apiKey = process.env.API_KEY;
  if (apiKey && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${apiKey}`);
  }

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
        target: targetUrl.toString(),
      },
      { status: 502 }
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
