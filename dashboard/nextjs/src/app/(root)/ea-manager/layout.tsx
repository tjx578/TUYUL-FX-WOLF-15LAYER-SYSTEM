import type { Metadata, PropsWithChildren } from "next";

export const metadata: Metadata = {
  title: "Agent Control",
  description: "EA agent health, regime scope, capital allocation, and governed restart.",
};

export default function AgentControlLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
