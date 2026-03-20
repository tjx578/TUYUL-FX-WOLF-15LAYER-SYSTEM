import type { Metadata } from "next";
import type { PropsWithChildren } from "react";

export const metadata: Metadata = {
  title: "Trade Desk",
  description: "Full trade lifecycle — INTENDED → PENDING → OPEN → CLOSED.",
};

export default function TradeDeskLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
