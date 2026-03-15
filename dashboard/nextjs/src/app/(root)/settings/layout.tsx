import type { Metadata } from "next";
import type { PropsWithChildren } from "react";

export const metadata: Metadata = {
  title: "System Constitution",
  description: "Single source of truth — governed config, lock model, scope hierarchy.",
};

export default function SystemConstitutionLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
