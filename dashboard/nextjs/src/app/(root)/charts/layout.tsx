import type { PropsWithChildren } from "react";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Live Charts | TUYUL FX",
  description: "Realtime candlestick charts with live price updates",
};

export default function ChartsLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
