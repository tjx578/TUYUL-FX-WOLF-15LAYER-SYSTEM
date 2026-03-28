import type { PropsWithChildren } from "react";
import { requireVerifiedSession } from "@/lib/serverAuth";
import DashboardShell from "@/components/layout/DashboardShell";
import BackgroundDecoration from "@/components/layout/BackgroundDecoration";

export const dynamic = "force-dynamic";

export default async function ControlLayout({ children }: PropsWithChildren) {
    const user = await requireVerifiedSession();

    return (
        <div
            className="relative min-h-screen text-text-primary overflow-x-hidden"
            style={{ backgroundColor: "#000000" }}
        >
            <BackgroundDecoration />
            <DashboardShell user={user}>{children}</DashboardShell>
        </div>
    );
}
