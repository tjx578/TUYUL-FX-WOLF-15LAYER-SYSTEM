import { NextRequest, NextResponse } from "next/server";
import { resolveDashboardUpstream } from "@/lib/server/dashboardTopology";
import { isAllowlistedReadPath } from "@/lib/server/readOnlyProxyPolicy";
import { validateSessionToken } from "@/lib/serverAuth";

function bearerToken(request: NextRequest): string {
  const match = /^Bearer\s+(.+)$/i.exec(
    request.headers.get("authorization") ?? "",
  );
  return match?.[1]?.trim() ?? "";
}

function deny(requestId: string): NextResponse {
  return NextResponse.json(
    { error: "Forbidden", code: "READ_ONLY_PROXY_BOUNDARY" },
    {
      status: 403,
      headers: {
        "cache-control": "no-store",
        "x-request-id": requestId,
      },
    },
  );
}

async function proxyRequest(
  request: NextRequest,
  path: string[],
): Promise<NextResponse> {
  const requestId =
    request.headers.get("x-request-id") || crypto.randomUUID();
  const joinedPath = path.join("/");

  // Method and exact-path containment run before auth or any upstream request.
  if (request.method !== "GET" || !isAllowlistedReadPath(joinedPath)) {
    return deny(requestId);
  }

  const token = bearerToken(request);
  if (!(await validateSessionToken(token))) {
    return NextResponse.json(
      { error: "Unauthorized", code: "INVALID_VIEWER_SESSION" },
      {
        status: 401,
        headers: {
          "cache-control": "no-store",
          "x-request-id": requestId,
        },
      },
    );
  }

  const upstream = resolveDashboardUpstream(joinedPath);
  if (!upstream || upstream.surface !== "bff") {
    return NextResponse.json(
      { error: "Viewer BFF is not configured", code: "BFF_MISCONFIGURED" },
      {
        status: 503,
        headers: {
          "cache-control": "no-store",
          "x-proxy-status": "misconfigured",
          "x-proxy-surface": "bff",
          "x-request-id": requestId,
        },
      },
    );
  }

  const targetUrl = new URL("/api/" + joinedPath, upstream.url);
  request.nextUrl.searchParams.forEach((value, key) => {
    targetUrl.searchParams.set(key, value);
  });

  const headers = new Headers({
    accept: "application/json",
    authorization: "Bearer " + token,
    "x-request-id": requestId,
  });

  const targetLabel = targetUrl.protocol + "//" + targetUrl.host;

  try {
    const response = await fetch(targetUrl.toString(), {
      method: "GET",
      headers,
      cache: "no-store",
      redirect: "error",
    });

    const responseHeaders = new Headers({
      "cache-control": "no-store",
      "content-type":
        response.headers.get("content-type") || "application/json",
      "x-proxy-target": targetLabel,
      "x-proxy-status": "ok",
      "x-proxy-surface": "bff",
      "x-request-id": requestId,
    });

    const bffCache = response.headers.get("x-bff-cache");
    if (bffCache) responseHeaders.set("x-bff-cache", bffCache);

    return new NextResponse(response.body, {
      status: response.status,
      headers: responseHeaders,
    });
  } catch {
    return NextResponse.json(
      { error: "Backend unavailable", code: "UPSTREAM_UNAVAILABLE" },
      {
        status: 502,
        headers: {
          "cache-control": "no-store",
          "x-proxy-target": targetLabel,
          "x-proxy-status": "error",
          "x-proxy-surface": "bff",
          "x-request-id": requestId,
        },
      },
    );
  }
}

type RouteContext = { params: Promise<{ path: string[] }> };

export async function GET(
  request: NextRequest,
  { params }: RouteContext,
): Promise<NextResponse> {
  return proxyRequest(request, (await params).path);
}

export async function POST(
  request: NextRequest,
  { params }: RouteContext,
): Promise<NextResponse> {
  return proxyRequest(request, (await params).path);
}

export async function PUT(
  request: NextRequest,
  { params }: RouteContext,
): Promise<NextResponse> {
  return proxyRequest(request, (await params).path);
}

export async function PATCH(
  request: NextRequest,
  { params }: RouteContext,
): Promise<NextResponse> {
  return proxyRequest(request, (await params).path);
}

export async function DELETE(
  request: NextRequest,
  { params }: RouteContext,
): Promise<NextResponse> {
  return proxyRequest(request, (await params).path);
}
