import type { Metadata, PropsWithChildren } from "next";

export const metadata: Metadata = {
  title: "Risk Command",
  description: "Breach detection, circuit breaker state, live drawdown feed.",
};

export default function RiskCommandLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
