import { NextRequest, NextResponse } from "next/server";
import { resolveDashboardUpstream } from "@/lib/server/dashboardTopology";
import { isAllowlistedReadPath } from "@/lib/server/readOnlyProxyPolicy";
import { fetchViewerProjection } from "@/lib/server/viewerProjection";
import { validateSessionToken } from "@/lib/serverAuth";

async function proxyRequest(request: NextRequest, path: string[]): Promise<NextResponse> {
  const requestId = crypto.randomUUID();
  const joinedPath = path.join("/");
  const headers = { "cache-control": "no-store", "x-request-id": requestId, "x-proxy-surface": "core-api" };
  const error = (status: number, code: string, message: string) => NextResponse.json(
    { error: message, code }, { status, headers },
  );

  // Deny extra paths, query parameters and all mutations before any fetch.
  if (request.method !== "GET" || !isAllowlistedReadPath(joinedPath) || request.nextUrl.search) {
    return error(403, "READ_ONLY_PROXY_BOUNDARY", "Forbidden");
  }
  const token = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization") ?? "")?.[1]?.trim() ?? "";
  if (!token || token.split(".").length !== 3) return error(401, "INVALID_VIEWER_SESSION", "Unauthorized");

  const upstream = resolveDashboardUpstream(joinedPath);
  if (!upstream || upstream.url === request.nextUrl.origin) {
    return error(503, "CORE_API_MISCONFIGURED", "Core API is not configured");
  }
  if (!(await validateSessionToken(token))) return error(401, "INVALID_VIEWER_SESSION", "Unauthorized");
  try {
    const payload = await fetchViewerProjection(upstream.url, joinedPath, token, requestId);
    return NextResponse.json(payload, { status: 200, headers });
  } catch {
    return error(502, "UPSTREAM_UNAVAILABLE", "Backend unavailable");
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
