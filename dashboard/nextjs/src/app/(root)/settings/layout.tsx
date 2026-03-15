import type { Metadata, PropsWithChildren } from "next";

export const metadata: Metadata = {
  title: "System Constitution",
  description: "Single source of truth — governed config, lock model, scope hierarchy.",
};

export default function SystemConstitutionLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
