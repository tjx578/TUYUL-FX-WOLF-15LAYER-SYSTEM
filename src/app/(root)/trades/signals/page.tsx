import { redirect } from "next/navigation";

// Legacy route - redirects to (control)/signals
export default function LegacySignalsRedirect() {
  redirect("/signals");
}
