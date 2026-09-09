import { NextResponse } from "next/server";

export async function GET(): Promise<NextResponse> {
  return NextResponse.json(
    {
      status: "ok",
      service: "dashboard-frontend",
      mode: "viewer",
    },
    { headers: { "cache-control": "no-store" } },
  );
}
