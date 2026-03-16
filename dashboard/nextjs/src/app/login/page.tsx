"use client";

import { Suspense, useState, useTransition } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AUTH_LOGIN } from "@/lib/endpoints";

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const callbackUrl = searchParams.get("callbackUrl") ?? "/";

  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    startTransition(async () => {
      try {
        const apiBase =
          process.env.NEXT_PUBLIC_API_BASE_URL ??
          process.env.NEXT_PUBLIC_API_URL ??
          "";

        const res = await fetch(`${apiBase}${AUTH_LOGIN}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ api_key: apiKey }),
          credentials: "include",
        });

        if (!res.ok) {
          const body = await res.json().catch(() => ({})) as { detail?: string };
          setError(body.detail ?? "Invalid API key. Please try again.");
          return;
        }

        const { token } = (await res.json()) as { token?: string };

        if (token) {
          await fetch("/api/set-session", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token }),
          });
        }

        router.replace(callbackUrl);
      } catch {
        setError("Network error. Check your connection and try again.");
      }
    });
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950">
      <div className="w-full max-w-sm rounded-2xl border border-white/10 bg-slate-900 p-8 shadow-xl">
        <div className="mb-8 text-center">
          <h1 className="text-xl font-semibold tracking-tight text-white">
            TUYUL FX
          </h1>
          <p className="mt-1 text-sm text-slate-400">WOLF-15 Terminal</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="api-key"
              className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-slate-400"
            >
              API Key
            </label>
            <input
              id="api-key"
              type="password"
              autoComplete="current-password"
              required
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Enter your API key"
              className="w-full rounded-lg border border-white/10 bg-slate-800 px-3 py-2.5 text-sm text-white placeholder-slate-500 outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500"
            />
          </div>

          {error && (
            <p className="rounded-lg bg-red-950/60 px-3 py-2 text-xs text-red-400">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={isPending || !apiKey.trim()}
            className="w-full rounded-lg bg-cyan-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isPending ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
