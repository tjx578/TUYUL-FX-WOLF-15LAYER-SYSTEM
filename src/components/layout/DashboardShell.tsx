"use client";

import type { PropsWithChildren } from "react";
import type { SessionUser } from "@/contracts/auth";
import { Providers } from "@/components/Providers";
import AuthBootstrap from "@/components/auth/AuthBootstrap";
import LivePipelineProvider from "@/components/LivePipelineProvider";
import ComplianceBanner from "@/components/feedback/ComplianceBanner";
import DegradationBanner from "@/components/feedback/DegradationBanner";
import Header from "@/components/layout/Header";
import WorkspaceManager from "@/components/layout/WorkspaceManager";
import Sidebar from "@/components/layout/Sidebar";
import RouteTransition from "@/components/layout/RouteTransition";

interface Props extends PropsWithChildren {
    user: SessionUser;
}

export default function DashboardShell({ user, children }: Props) {
    return (
        <Providers>
            <AuthBootstrap user={user} />
            <LivePipelineProvider />
            <div className="relative z-10 flex min-h-screen">
                <Sidebar />
                <main
                    className="flex-1 overflow-auto"
                    style={{
                        marginLeft: "var(--sidebar-w)",
                        minHeight: "100vh",
                        padding: "32px 40px",
                        background: "#000000",
                    }}
                >
                    <Header />
                    <DegradationBanner />
                    <ComplianceBanner />
                    <RouteTransition>{children}</RouteTransition>
                    <WorkspaceManager />
                </main>
            </div>
        </Providers>
    );
}
