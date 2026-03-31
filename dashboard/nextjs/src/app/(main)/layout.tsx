import type { PropsWithChildren } from "react";
import { requireVerifiedSession } from "@/lib/serverAuth";
import DashboardShell from "@/components/layout/DashboardShell";

export const dynamic = "force-dynamic";

export default async function MainLayout({ children }: PropsWithChildren) {
  const user = await requireVerifiedSession();
  return (
    <div
      className="relative min-h-screen text-text-primary overflow-x-hidden"
      style={{ backgroundColor: "#0a0b0d" }}
    >
      <DashboardShell user={user}>{children}</DashboardShell>
    </div>
  );
}
