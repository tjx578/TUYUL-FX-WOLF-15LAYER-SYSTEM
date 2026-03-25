import type { PropsWithChildren } from "react";

export const dynamic = "force-dynamic";

export default function AdminLayout({ children }: PropsWithChildren) {
  return <>{children}</>;
}
