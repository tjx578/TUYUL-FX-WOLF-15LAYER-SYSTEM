import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Agent Manager | TUYUL FX",
  description: "EA instance health, profiles, logs, and command control.",
};

export default function EAManagerLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
