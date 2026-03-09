import type { PropsWithChildren } from "react";
import { Providers } from "@/components/Providers";
import AuthBootstrap from "@/components/auth/AuthBootstrap";
import ComplianceBanner from "@/components/feedback/ComplianceBanner";
import Header from "@/components/layout/Header";
import PreferencesPanel from "@/components/layout/PreferencesPanel";
import Sidebar from "@/components/layout/Sidebar";
import RouteTransition from "@/components/layout/RouteTransition";
import { requireVerifiedSession } from "@/lib/serverAuth";

export default async function RootLayout({ children }: PropsWithChildren) {
  const user = await requireVerifiedSession();

  return (
    <div className="relative min-h-screen bg-bg-primary text-text-primary overflow-x-hidden">
      <div
        className="pointer-events-none fixed -top-80 -right-80 w-[900px] h-[900px] rounded-full z-0"
        style={{ background: "rgba(0,229,255,0.10)", filter: "blur(220px)" }}
      />

      <div
        className="pointer-events-none fixed -bottom-80 -left-80 w-[900px] h-[900px] rounded-full z-0"
        style={{ background: "rgba(255,122,0,0.10)", filter: "blur(220px)" }}
      />

      <div
        className="pointer-events-none fixed inset-0 z-0"
        style={{
          background:
            "radial-gradient(circle at center, rgba(255,255,255,0.04) 0%, transparent 60%)",
        }}
      />

      <div className="pointer-events-none fixed inset-0 z-0 opacity-[0.04] bg-[url('/grid.png')]" />
      <div className="pointer-events-none fixed inset-0 z-0 opacity-[0.025] bg-[url('/noise.png')]" />
      <div
        className="pointer-events-none fixed inset-0 z-0"
        style={{ boxShadow: "inset 0 0 200px rgba(0,0,0,0.8)" }}
      />

      <Providers>
        <AuthBootstrap user={user} />
        <div className="relative z-10 flex min-h-screen">
          <Sidebar />
          <main
            className="flex-1 overflow-auto"
            style={{ marginLeft: "var(--sidebar-w)", minHeight: "100vh", padding: "32px 40px" }}
          >
            <Header />
            <ComplianceBanner />
            <RouteTransition>{children}</RouteTransition>
            <PreferencesPanel />
          </main>
        </div>
      </Providers>
    </div>
  );
}
