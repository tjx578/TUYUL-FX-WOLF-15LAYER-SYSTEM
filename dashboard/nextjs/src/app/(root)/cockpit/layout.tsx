import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Portfolio Cockpit | TUYUL FX",
  description: "Portfolio-level overview across accounts, pipeline, and governance state.",
};

export default function CockpitLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
