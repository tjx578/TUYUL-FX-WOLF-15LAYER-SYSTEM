import type { Metadata } from "next";
import type { PropsWithChildren } from "react";

export const metadata: Metadata = {
  title: "Capital Accounts",
  description: "Capital deployment surface — equity, drawdown, and account readiness.",
};

export default function CapitalAccountsLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
