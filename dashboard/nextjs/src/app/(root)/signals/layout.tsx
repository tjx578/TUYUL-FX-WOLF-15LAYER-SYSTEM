import type { Metadata } from "next";
import type { PropsWithChildren } from "react";

export const metadata: Metadata = {
  title: "Signal Explorer",
  description: "Browse, filter, and inspect all L12 verdicts — exploratory, not execution queue.",
};

export default function SignalExplorerLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
