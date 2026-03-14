import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

// Dashboard is unrestricted — owner has direct access without any auth gate.
// All auth redirect logic has been removed; every request passes through.
export function middleware(_request: NextRequest) {
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon\\.ico|api/).*)",
  ],
};
