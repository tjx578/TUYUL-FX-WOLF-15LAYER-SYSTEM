import { redirect } from "next/navigation";

// Dashboard is unrestricted — redirect anyone who lands on /login straight to /.
export default function LoginPage() {
  redirect("/");
}
