import type { Metadata, PropsWithChildren } from "next";

export const metadata: Metadata = {
  title: "Operator Journal",
  description: "Operator notes, intervention reasoning, and decision quality log.",
};

export default function OperatorJournalLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
