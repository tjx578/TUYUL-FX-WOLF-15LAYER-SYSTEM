import { redirect } from "next/navigation";

// /dashboard is deprecated — redirect to Command Center
// Blueprint PR-1: remove route ambiguity ("dashboard inside a dashboard")
export default function DashboardDeprecatedPage() {
  redirect("/");
}
