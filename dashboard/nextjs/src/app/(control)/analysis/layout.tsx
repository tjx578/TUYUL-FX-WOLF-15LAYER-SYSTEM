import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Market Analysis | TUYUL FX",
  description: "Charts, probability health, and live price monitoring.",
};

export default function AnalysisLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
