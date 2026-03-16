"use client";

// ============================================================
// TUYUL FX Wolf-15 — Client Providers (SWR, etc.)
// ============================================================

import { SWRConfig } from "swr";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig
      value={{
        revalidateOnFocus: false,
        shouldRetryOnError: true,
        // Increase retry count — 3 exhausts too quickly on cold starts / slow Railway wake-up.
        errorRetryCount: 8,
        // Exponential backoff capped at 30 s so streams recover after backend restarts.
        errorRetryInterval: 3000,
        onErrorRetry: (error, _key, _config, revalidate, { retryCount }) => {
          // Do not retry on 401/403 — re-auth is required, retrying is pointless.
          if (error?.message?.includes("401") || error?.message?.includes("403")) return;
          // Do not retry on 404 — endpoint doesn't exist, retrying won't help.
          if (error?.message?.includes("404")) return;
          // Exponential backoff: 3s, 6s, 12s, 24s, 30s, 30s …
          const delay = Math.min(3000 * Math.pow(2, retryCount), 30_000);
          setTimeout(() => revalidate({ retryCount }), delay);
        },
      }}
    >
      {children}
    </SWRConfig>
  );
}
