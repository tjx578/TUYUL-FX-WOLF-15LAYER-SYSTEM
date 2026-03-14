import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

/**
 * Middleware — auth redirect disabled.
 *
 * Cookie-based session checks are unreliable across Vercel <> Railway domains
 * (cross-site Set-Cookie is blocked by browsers). Auth is enforced inside
 * server components via requireVerifiedSession() in (root)/layout.tsx using
 * the Authorization: Bearer header forwarded from the client.
 *
 * TODO: Re-enable cookie guard once session cookie domain is aligned.
 */
export function middleware(_request: NextRequest) {
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon\\.ico|api/).*)",
  ],
};
