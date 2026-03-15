import type { Metadata, PropsWithChildren } from "next";

export const metadata: Metadata = {
  title: "Compliance Hub",
  description: "Prop firm constraints, enforcement mode, phase status, and why-blocked context.",
};

export default function ComplianceHubLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
