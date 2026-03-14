"use client";

import { useRouter } from "next/navigation";
import { useState, useEffect, useCallback, type FormEvent } from "react";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [apiKey, setApiKey] = useState<string>(() =>
    (process.env.NEXT_PUBLIC_API_KEY ?? "").toString().trim(),
  );

  useEffect(() => {
    if (process.env.NEXT_PUBLIC_API_KEY) {
      setApiKey(process.env.NEXT_PUBLIC_API_KEY.trim());
    }
  }, []);

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
        // Use relative /api/auth/session — Next.js rewrite proxies this to the
        // backend without requiring NEXT_PUBLIC_* env vars in the browser bundle.
        const requestHeaders = {
          authorization: `Bearer ${trimmedKey}`,
          origin: window.location.origin,
          cookie: document.cookie || "(none)",
        };
        console.log("[v0] LOGIN request headers →", JSON.stringify(requestHeaders, null, 2));

        const res = await fetch(`/api/auth/session`, {
          method: "GET",
          headers: { authorization: requestHeaders.authorization },
          credentials: "include",
        });

        // Log response headers (set-cookie, etc.)
        const responseHeaders: Record<string, string> = {};
        res.headers.forEach((value, key) => { responseHeaders[key] = value; });
        console.log("[v0] LOGIN response status:", res.status, res.statusText);
        console.log("[v0] LOGIN response headers →", JSON.stringify(responseHeaders, null, 2));

        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          setError(
            (body as { detail?: string })?.detail ||
            "Invalid API key or session could not be established"
          );
          setLoading(false);
          return;
        }

        // Persist the API key in sessionStorage so axios interceptors can attach it.
        sessionStorage.setItem("api_key", trimmedKey);

        console.log("[v0] LOGIN redirect → / (status: 200 → push)");
        router.push("/");
        router.refresh();
      } catch (err) {
        console.log("[v0] LOGIN fetch error:", err);
        setError("Could not reach the API server. Check INTERNAL_API_URL is set.");
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
