// Owner mode — no authentication required.
// Redirect immediately to the dashboard root.
import { redirect } from "next/navigation";

export default function LoginPage() {
  redirect("/");
}
