import type { PropsWithChildren } from "react";
import { redirect } from "next/navigation";
import { getVerifiedSessionUser } from "@/lib/serverAuth";

export const dynamic = "force-dynamic";

export default async function MainLayout({ children }: PropsWithChildren) {
  const user = await getVerifiedSessionUser();
  if (!user) redirect("/login");

  return children;
}
