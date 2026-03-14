import type { Metadata } from "next";
import QueryProvider from "@/components/providers/QueryProvider";
import SessionExpiryModal from "@/components/auth/SessionExpiryModal";
import ToastViewport from "@/components/feedback/ToastViewport";
import "./globals.css";

export const metadata: Metadata = {
  title: "WOLF-15 Terminal | TUYUL FX",
  description: "Institutional-grade multi-layer prop-firm trading terminal with real-time pipeline analytics, risk governance, and compliance automation.",
  keywords: ["forex", "trading", "wolf-15", "prop firm", "institutional", "pipeline"],
  authors: [{ name: "TUYUL FX" }],
  themeColor: "#050a14",
  viewport: "width=device-width, initial-scale=1",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <QueryProvider>
          {children}
          <SessionExpiryModal />
          <ToastViewport />
        </QueryProvider>
      </body>
    </html>
  );
}

