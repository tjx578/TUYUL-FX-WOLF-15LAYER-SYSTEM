import type { Metadata } from "next";
import type { PropsWithChildren } from "react";

export const metadata: Metadata = {
  title: "Market",
  description: "Live charts, economic calendar, market news, and price watchlist.",
};

export default function MarketLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
