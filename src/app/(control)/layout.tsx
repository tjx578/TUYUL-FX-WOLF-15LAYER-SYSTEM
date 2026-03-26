import type { PropsWithChildren } from "react";
import { requireVerifiedSession } from "@/lib/serverAuth";
import DashboardShell from "@/components/layout/DashboardShell";

export const dynamic = "force-dynamic";

export default async function ControlLayout({ children }: PropsWithChildren) {
    const user = await requireVerifiedSession();

    return (
        <div
            className="relative min-h-screen text-text-primary overflow-x-hidden"
            style={{ backgroundColor: "#000000" }}
        >
            {/* Decorative background: cyan glow top-right */}
            <div
                className="pointer-events-none fixed -top-80 -right-80 w-[900px] h-[900px] rounded-full z-0"
                style={{
                    background: "rgba(0,229,255,0.10)",
                    filter: "blur(220px)",
                }}
            />
            {/* Decorative background: orange glow bottom-left */}
            <div
                className="pointer-events-none fixed -bottom-80 -left-80 w-[900px] h-[900px] rounded-full z-0"
                style={{
                    background: "rgba(255,122,0,0.10)",
                    filter: "blur(220px)",
                }}
            />
            {/* Radial gradient overlay */}
            <div
                className="pointer-events-none fixed inset-0 z-0"
                style={{
                    background:
                        "radial-gradient(circle at center, rgba(255,255,255,0.04) 0%, transparent 60%)",
                }}
            />
            {/* Grid pattern */}
            <div
                className="pointer-events-none fixed inset-0 z-0 opacity-[0.04]"
                style={{
                    backgroundImage: `url("data:image/svg+xml,%3Csvg width='40' height='40' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M0 0h40v40H0z' fill='none' stroke='%23ffffff' stroke-width='0.5'/%3E%3C/svg%3E")`,
                    backgroundRepeat: "repeat",
                }}
            />
            {/* Noise texture */}
            <div
                className="pointer-events-none fixed inset-0 z-0 opacity-[0.025]"
                style={{
                    backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.5'/%3E%3C/svg%3E")`,
                    backgroundRepeat: "repeat",
                }}
            />
            {/* Vignette */}
            <div
                className="pointer-events-none fixed inset-0 z-0"
                style={{ boxShadow: "inset 0 0 200px rgba(0,0,0,0.8)" }}
            />

            <DashboardShell user={user}>{children}</DashboardShell>
        </div>
    );
}
