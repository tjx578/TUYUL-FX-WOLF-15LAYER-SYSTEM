import { NextRequest, NextResponse } from "next/server";

/**
 * Dynamic health check proxy that reads backend URL at runtime.
 */

function getBackendUrl(): string {
  const url =
    process.env.INTERNAL_API_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    process.env.API_BASE_URL ||
    (process.env.API_DOMAIN ? `https://${process.env.API_DOMAIN}` : "") ||
    "";

  if (!url) {
    if (process.env.NODE_ENV === "development") {
      return "http://localhost:8000";
    }
    throw new Error("[health] Missing backend URL");
  }

  return url.replace(/\/+$/, "").replace(/\/api$/, "");
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const backendUrl = getBackendUrl();
  const targetUrl = `${backendUrl}/health`;

  try {
    const response = await fetch(targetUrl, {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
    });

    const data = await response.json();

    return NextResponse.json(data, {
      status: response.status,
    });
  } catch (error) {
    console.error(`[health] Failed to fetch ${targetUrl}:`, error);
    return NextResponse.json(
      {
        status: "error",
        detail: error instanceof Error ? error.message : "Connection failed",
      },
      { status: 502 }
    );
  }
}
