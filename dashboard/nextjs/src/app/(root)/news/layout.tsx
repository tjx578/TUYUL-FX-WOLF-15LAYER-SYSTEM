import type { Metadata } from "next";
import type { PropsWithChildren } from "react";

export const metadata: Metadata = {
  title: "Market Events",
  description: "Economic calendar intelligence — HIGH impact governs news lock and signal eligibility.",
};

export default function MarketEventsLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
