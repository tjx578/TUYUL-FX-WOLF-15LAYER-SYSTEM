// Login page — checks for existing session before redirecting.
// Prevents redirect loop: / → /login → / → /login
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

const SESSION_COOKIE = "wolf15_session";

export default async function LoginPage() {
  // 1. If session cookie exists, redirect to dashboard
  const cookieStore = await cookies();
  const session = cookieStore.get(SESSION_COOKIE)?.value;
  if (session) {
    redirect("/");
  }

  // 2. If API_KEY env var exists (owner-mode), redirect through the
  //    owner-session route handler which CAN set cookies (Server Components cannot).
  const apiKey = process.env.API_KEY?.trim();
  if (apiKey) {
    redirect("/api/auth/owner-session");
  }

  // 3. No session, no API_KEY → render setup instructions
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#080E1A",
        color: "#E2E8F0",
        fontFamily: "monospace",
        padding: 24,
      }}
    >
      <div
        style={{
          maxWidth: 480,
          width: "100%",
          display: "flex",
          flexDirection: "column",
          gap: 20,
        }}
      >
        <h1 style={{ fontSize: 20, fontWeight: 800, letterSpacing: "0.08em", margin: 0 }}>
          WOLF-15 SETUP REQUIRED
        </h1>
        <p style={{ fontSize: 13, color: "#94A3B8", margin: 0, lineHeight: 1.6 }}>
          No session found. Set the following environment variable and restart:
        </p>
        <div
          style={{
            background: "#0F172A",
            border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: 8,
            padding: "16px 20px",
            fontSize: 13,
          }}
        >
          <code style={{ color: "#00F5A0" }}>API_KEY=&lt;your-jwt-or-api-key&gt;</code>
        </div>
        <div style={{ fontSize: 11, color: "#64748B", lineHeight: 1.6 }}>
          <p style={{ margin: "0 0 8px" }}>For Vercel deployments, add these env vars in Settings → Environment Variables:</p>
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            <li><code>INTERNAL_API_URL</code> — Railway backend URL</li>
            <li><code>NEXT_PUBLIC_WS_BASE_URL</code> — WebSocket base URL (wss://...)</li>
            <li><code>API_KEY</code> — JWT or API key for owner-mode auth</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
