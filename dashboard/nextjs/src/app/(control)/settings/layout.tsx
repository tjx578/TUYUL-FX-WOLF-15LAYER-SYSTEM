import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Settings Center | TUYUL FX",
  description: "Profiles, overrides, locks, and effective configuration governance.",
};

export default function SettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
