import type { Metadata } from "next";
import type { PropsWithChildren } from "react";

export const metadata: Metadata = {
  title: "Operator Journal",
  description: "Operator notes, intervention reasoning, and decision quality log.",
};

export default function OperatorJournalLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
