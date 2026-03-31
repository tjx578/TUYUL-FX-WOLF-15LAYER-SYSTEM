import type { Metadata } from "next";
import type { PropsWithChildren } from "react";

export const metadata: Metadata = {
  title: "Settings Center",
  description: "Profiles, overrides, locks, and effective configuration governance.",
};

export default function SettingsLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
