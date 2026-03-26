import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Prop Firm Control | TUYUL FX",
  description: "Program compliance, phase progress, and account-level constraints.",
};

export default function PropFirmLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
