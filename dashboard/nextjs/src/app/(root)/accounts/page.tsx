import { redirect } from "next/navigation";

// Legacy route - redirects to (control)/accounts
export default function LegacyAccountsPage() {
  redirect("/accounts");
}
