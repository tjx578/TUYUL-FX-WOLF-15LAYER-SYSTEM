import { redirect } from "next/navigation";

// Legacy route - redirects to (control)/journal
export default function LegacyJournalPage() {
  redirect("/journal");
}
