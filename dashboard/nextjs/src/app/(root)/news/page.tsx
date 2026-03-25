import { redirect } from "next/navigation";

// Legacy route - redirects to (control)/news
export default function LegacyNewsPage() {
  redirect("/news");
}
