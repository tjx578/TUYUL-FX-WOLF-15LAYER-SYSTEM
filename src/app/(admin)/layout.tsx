import type { PropsWithChildren } from "react";
import { ADMIN_ROLES } from "@/lib/auth";
import { requireVerifiedSession } from "@/lib/serverAuth";

// Force all admin routes to be serverless (dynamic) — never ISR-cached.
// Prevents stale auth and stale data (e.g. /audit showing cached entries).
export const dynamic = "force-dynamic";

export default async function AdminLayout({ children }: PropsWithChildren) {
  await requireVerifiedSession(ADMIN_ROLES);
  return children;
}
