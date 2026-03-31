"use client";

import type { PropsWithChildren } from "react";
import type { SessionUser } from "@/contracts/auth";
import AuthBootstrap from "@/components/auth/AuthBootstrap";
import LivePipelineProvider from "@/components/LivePipelineProvider";
import ComplianceBanner from "@/components/feedback/ComplianceBanner";
import DegradationBanner from "@/components/feedback/DegradationBanner";
import WorkspaceManager from "@/components/layout/WorkspaceManager";
import { SidebarV2 } from "@/components/layout/SidebarV2";
import { Topbar } from "@/components/layout/Topbar";
import RouteTransition from "@/components/layout/RouteTransition";

interface Props extends PropsWithChildren {
    user: SessionUser;
}

export default function DashboardShell({ user, children }: Props) {
    return (
        <>
            <AuthBootstrap user={user} />
            <LivePipelineProvider />
            <div style={{ display: "grid", gridTemplateColumns: "240px 1fr", minHeight: "100vh" }}>
                <SidebarV2 />
                <main
                    style={{
                        marginLeft: 240,
                        padding: 16,
                        background: "linear-gradient(180deg, #0a0b0d, #0d1016 40%, #0a0b0d)",
                        minHeight: "100vh",
                    }}
                >
                    <Topbar />
                    <DegradationBanner />
                    <ComplianceBanner />
                    <RouteTransition>{children}</RouteTransition>
                    <WorkspaceManager />
                </main>
            </div>
        </>
    );
}
