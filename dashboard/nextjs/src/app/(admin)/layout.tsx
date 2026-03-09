import type { PropsWithChildren } from "react";
import { ADMIN_ROLES } from "@/lib/auth";
import { requireVerifiedSession } from "@/lib/serverAuth";

export default async function AdminLayout({ children }: PropsWithChildren) {
  await requireVerifiedSession(ADMIN_ROLES);
  return children;
}
