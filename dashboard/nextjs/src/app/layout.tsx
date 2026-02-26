// ============================================================
// TUYUL FX Wolf-15 — Root Layout
// ============================================================

type AppMetadata = {
  title: string;
  description: string;
};

import { Providers } from "@/components/Providers";
import { Sidebar } from "@/components/Sidebar";
import "./globals.css";

export const metadata: AppMetadata = {
  title: "TUYUL FX — Wolf-15 Dashboard",
  description: "Institutional-grade forex trading dashboard",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="relative min-h-screen bg-bg-primary text-text-primary overflow-x-hidden">

        {/* ─── LIGHTING LAYER 1: Ambient Glow Top Right (Cyan) ─── */}
        <div className="pointer-events-none fixed -top-80 -right-80 w-[900px] h-[900px] rounded-full z-0"
          style={{ background: 'rgba(0,229,255,0.10)', filter: 'blur(220px)' }} />

        {/* ─── LIGHTING LAYER 2: Ambient Glow Bottom Left (Orange) ─── */}
        <div className="pointer-events-none fixed -bottom-80 -left-80 w-[900px] h-[900px] rounded-full z-0"
          style={{ background: 'rgba(255,122,0,0.10)', filter: 'blur(220px)' }} />

        {/* ─── LIGHTING LAYER 3: Center Radial Depth ─── */}
        <div className="pointer-events-none fixed inset-0 z-0"
          style={{ background: 'radial-gradient(circle at center, rgba(255,255,255,0.04) 0%, transparent 60%)' }} />

        {/* ─── LIGHTING LAYER 4: Subtle Tech Grid ─── */}
        <div className="pointer-events-none fixed inset-0 z-0 opacity-[0.04] bg-[url('/grid.png')]" />

        {/* ─── LIGHTING LAYER 5: Film Grain / Noise Texture ─── */}
        <div className="pointer-events-none fixed inset-0 z-0 opacity-[0.025] bg-[url('/noise.png')]" />

        {/* ─── LIGHTING LAYER 6: Edge Vignette ─── */}
        <div className="pointer-events-none fixed inset-0 z-0"
          style={{ boxShadow: 'inset 0 0 200px rgba(0,0,0,0.8)' }} />

        {/* ─── APP SHELL (above all lighting layers) ─── */}
        <Providers>
          <div className="relative z-10 flex min-h-screen">
            <Sidebar />
            <main
              style={{
                flex: 1,
                marginLeft: "var(--sidebar-w)",
                minHeight: "100vh",
                overflow: "auto",
              }}
            >
              {children}
            </main>
          </div>
        </Providers>

      </body>
    </html>
  );
}
