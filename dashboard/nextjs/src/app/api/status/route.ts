import { NextResponse } from "next/server";

/**
 * Direct core status access is retired in the G4 viewer profile. The user-facing
 * page reads only the three exact BFF projections through /api/proxy.
 */
export async function GET(): Promise<NextResponse> {
  return NextResponse.json(
    { error: "Direct operator status is unavailable on the viewer surface" },
    { status: 403, headers: { "cache-control": "no-store" } },
  );
}
