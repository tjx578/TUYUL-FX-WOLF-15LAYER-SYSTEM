import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import ViewerLoginForm from "./ViewerLoginForm";
import { validateSessionToken } from "@/lib/serverAuth";

const SESSION_COOKIE = "wolf15_session";

export default async function LoginPage() {
  const cookieStore = await cookies();
  const session = cookieStore.get(SESSION_COOKIE)?.value;

  if (session && (await validateSessionToken(session))) {
    redirect("/");
  }

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        background:
          "radial-gradient(circle at 15% 10%, rgba(163,230,53,0.10), transparent 32%), #070b12",
        color: "#e2e8f0",
        padding: 24,
      }}
    >
      <section
        style={{
          width: "min(100%, 460px)",
          border: "1px solid rgba(148,163,184,0.20)",
          borderRadius: 18,
          background: "rgba(15,23,42,0.90)",
          boxShadow: "0 24px 80px rgba(0,0,0,0.35)",
          padding: 28,
        }}
      >
        <div
          style={{
            color: "#a3e635",
            fontSize: 11,
            fontWeight: 800,
            letterSpacing: "0.14em",
          }}
        >
          WOLF15 / VIEWER
        </div>
        <h1
          style={{
            margin: "12px 0 8px",
            color: "#f8fafc",
            fontSize: 26,
            letterSpacing: "-0.03em",
          }}
        >
          Read-only observability
        </h1>
        <p
          style={{
            margin: "0 0 22px",
            color: "#94a3b8",
            fontSize: 13,
            lineHeight: 1.65,
          }}
        >
          Sign in with a scoped viewer JWT. This surface cannot send trading,
          risk, EA, execution, or broker commands.
        </p>
        <ViewerLoginForm />
      </section>
    </main>
  );
}
