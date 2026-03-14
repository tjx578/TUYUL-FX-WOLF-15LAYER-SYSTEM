"use client";

import { useRouter } from "next/navigation";
import { useState, useCallback, type FormEvent } from "react";
import { AUTH_LOGIN } from "@/lib/endpoints";
import { setToken } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [apiKey, setApiKey] = useState("");

  const handleSubmit = useCallback(
    async (e: FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      setError(null);
      setLoading(true);

      // Read the key directly from the form so we always get the current value,
      // regardless of any stale closure over `apiKey` state.
      const form = e.currentTarget as HTMLFormElement;
      const formData = new FormData(form);
      const trimmedKey = ((formData.get("apiKey") as string) ?? apiKey).trim();

      if (!trimmedKey) {
        setError("API key is required");
        setLoading(false);
        return;
      }

      try {
        // POST to /api/auth/login via Next.js rewrite proxy (relative path).
        // No base URL needed — next.config.js rewrites /api/* to the backend.
        const res = await fetch(AUTH_LOGIN, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ api_key: trimmedKey }),
        });

        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          setError(
            (body as { detail?: string })?.detail ||
            "Invalid API key or session could not be established"
          );
          setLoading(false);
          return;
        }

        const data = await res.json().catch(() => ({})) as { token?: string };

        // The token to persist — prefer the JWT from response body, else raw API key.
        const sessionToken = data.token ?? trimmedKey;

        // 1. Store client-side for WebSocket auth and axios interceptor.
        setToken(sessionToken);
        sessionStorage.setItem("api_key", sessionToken);

        // 2. Set a first-party HttpOnly cookie on the Vercel domain via a
        //    Next.js API route so server components can read it on navigation.
        //    (Cross-site cookies from Railway are blocked by browsers.)
        await fetch("/api/set-session", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: sessionToken }),
        });

        router.push("/");
        router.refresh();
      } catch (err) {
        console.error("[v0] LOGIN fetch error:", err);
        setError("Could not reach the API server. Check API_BASE_URL is set.");
        setLoading(false);
      }
    },
    [router, apiKey],
  );

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg-primary text-text-primary">
      <div className="w-full max-w-sm space-y-6 rounded-xl border border-white/10 bg-white/5 p-8 shadow-2xl backdrop-blur">
        <h1 className="text-center text-2xl font-bold tracking-tight">
          TUYUL FX Terminal
        </h1>
        <p className="text-center text-sm text-white/50">
          Enter your API key to continue
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <input
            name="apiKey"
            type="password"
            autoComplete="off"
            placeholder="API Key"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            className="w-full rounded-lg border border-white/10 bg-white/5 px-4 py-2.5 text-sm outline-none placeholder:text-white/30 focus:border-cyan-400/60"
          />

          {error && (
            <p className="text-sm text-red-400">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-lg bg-cyan-500 py-2.5 text-sm font-semibold text-black transition hover:bg-cyan-400 disabled:opacity-50"
          >
            {loading ? "Authenticating…" : "Sign In"}
          </button>
        </form>
      </div>
    </div>
  );
}
