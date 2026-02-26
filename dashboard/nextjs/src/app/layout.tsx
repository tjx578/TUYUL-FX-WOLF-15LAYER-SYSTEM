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
      <body>
        <Providers>
          <div
            style={{
              display: "flex",
              minHeight: "100vh",
              background: "var(--bg-base)",
            }}
          >
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
