import type { Metadata, PropsWithChildren } from "next";

export const metadata: Metadata = {
  title: "Market Events",
  description: "Economic calendar intelligence — HIGH impact governs news lock and signal eligibility.",
};

export default function MarketEventsLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
