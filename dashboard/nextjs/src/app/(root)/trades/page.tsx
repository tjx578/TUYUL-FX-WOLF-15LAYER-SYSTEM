import { redirect } from "next/navigation";

// Legacy route - redirects to (control)/trades
export default function LegacyTradesPage() {
  redirect("/trades");
}
