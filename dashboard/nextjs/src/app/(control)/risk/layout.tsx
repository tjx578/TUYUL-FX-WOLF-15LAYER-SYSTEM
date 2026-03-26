import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Risk Monitor | TUYUL FX",
  description: "Drawdown tracking, circuit breaker status, and account risk governance.",
};

export default function RiskLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
