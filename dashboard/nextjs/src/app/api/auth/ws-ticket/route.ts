import { NextResponse } from "next/server";

/**
 * WebSocket ticket export is disabled for the G4 viewer surface. Returning a
 * raw bearer credential to browser JavaScript would break the HttpOnly boundary.
 */
export async function GET(): Promise<NextResponse> {
  return NextResponse.json(
    { error: "WebSocket access is not available on the viewer dashboard" },
    { status: 403, headers: { "cache-control": "no-store" } },
  );
}
