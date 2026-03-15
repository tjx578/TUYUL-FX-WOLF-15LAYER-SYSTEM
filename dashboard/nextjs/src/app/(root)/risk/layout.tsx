import type { Metadata } from "next";
import type { PropsWithChildren } from "react";

export const metadata: Metadata = {
  title: "Risk Command",
  description: "Breach detection, circuit breaker state, live drawdown feed.",
};

export default function RiskCommandLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
