import type { Metadata, PropsWithChildren } from "next";

export const metadata: Metadata = {
  title: "Trade Desk",
  description: "Full trade lifecycle — INTENDED → PENDING → OPEN → CLOSED.",
};

export default function TradeDeskLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
