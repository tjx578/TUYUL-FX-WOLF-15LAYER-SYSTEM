import type { Metadata } from "next";
import type { PropsWithChildren } from "react";

export const metadata: Metadata = {
  title: "L12 Signal Board",
  description: "Layer-12 constitutional verdict signal board — grid/table views with full gate analysis.",
};

export default function SignalExplorerLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
