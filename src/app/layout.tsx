import type { Metadata, Viewport } from "next";
import { QueryProvider } from "@/components/providers/QueryProvider";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "TUYUL FX | WOLF-15 Terminal",
    template: "%s — TUYUL FX",
  },
  description:
    "Institutional-grade multi-layer prop-firm control surface: Command Center, Signal Board, Risk Command, Trade Desk, and governed compliance.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#050a14",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
