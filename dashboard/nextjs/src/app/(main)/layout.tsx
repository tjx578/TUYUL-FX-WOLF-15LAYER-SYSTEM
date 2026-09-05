import type { PropsWithChildren } from "react";
import { redirect } from "next/navigation";
import { getVerifiedSessionUser } from "@/lib/serverAuth";

export const dynamic = "force-dynamic";

export default async function MainLayout({ children }: PropsWithChildren) {
  const user = await getVerifiedSessionUser();
  if (!user) redirect("/login");

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#070b12",
        color: "#e2e8f0",
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
          borderBottom: "1px solid rgba(148,163,184,0.16)",
          background: "rgba(7,11,18,0.94)",
          padding: "14px clamp(18px, 4vw, 48px)",
        }}
      >
        <div>
          <div
            style={{
              color: "#a3e635",
              fontSize: 11,
              fontWeight: 900,
              letterSpacing: "0.14em",
            }}
          >
            WOLF15 / DASHBOARD
          </div>
          <div style={{ marginTop: 3, color: "#64748b", fontSize: 11 }}>
            OBSERVATIONAL_ONLY · NO EXECUTION AUTHORITY
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ color: "#cbd5e1", fontSize: 12 }}>
            {user.name || user.email}
          </div>
          <div
            style={{
              marginTop: 3,
              color: "#a3e635",
              fontSize: 10,
              fontWeight: 800,
              letterSpacing: "0.12em",
            }}
          >
            VIEWER · READ ONLY
          </div>
        </div>
      </header>
      {children}
    </div>
  );
}
