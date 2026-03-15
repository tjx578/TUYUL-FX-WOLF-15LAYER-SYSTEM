import type { Metadata, PropsWithChildren } from "next";

export const metadata: Metadata = {
  title: "Capital Accounts",
  description: "Capital deployment surface — equity, drawdown, and account readiness.",
};

export default function CapitalAccountsLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
