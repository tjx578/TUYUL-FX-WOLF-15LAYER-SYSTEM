import type { Metadata } from "next";
import type { PropsWithChildren } from "react";

export const metadata: Metadata = {
  title: "Signal Board",
  description: "Urgency-ranked executable signals — TAKE, SKIP, monitor state grouping.",
};

export default function SignalBoardLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
