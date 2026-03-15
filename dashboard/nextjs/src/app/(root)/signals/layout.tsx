import type { Metadata, PropsWithChildren } from "next";

export const metadata: Metadata = {
  title: "Signal Explorer",
  description: "Browse, filter, and inspect all L12 verdicts — exploratory, not execution queue.",
};

export default function SignalExplorerLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
