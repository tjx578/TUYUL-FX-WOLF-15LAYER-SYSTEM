import type { Metadata } from "next";
import type { PropsWithChildren } from "react";

export const metadata: Metadata = {
  title: "Risk Monitor",
  description: "Drawdown tracking, circuit breaker status, and account risk governance.",
};

export default function RiskLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
