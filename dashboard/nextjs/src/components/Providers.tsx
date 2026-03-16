"use client";

// ============================================================
// TUYUL FX Wolf-15 — Client Providers (SWR, etc.)
// Smart retry policy: skip 401/403 (auth errors are not transient),
// retry network/server errors up to 3 times with 1.5s delay.
// ============================================================

import { SWRConfig } from "swr";
import { HttpError } from "@/lib/fetcher";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig
      value={{
        revalidateOnFocus: false,
        revalidateOnReconnect: true,
        dedupingInterval: 15_000,
        shouldRetryOnError: true,
        errorRetryCount: 3,
        onErrorRetry: (error, _key, _config, revalidate, { retryCount }) => {
          // Skip retry for auth errors — they are not transient
          if (error instanceof HttpError && (error.status === 401 || error.status === 403)) {
            return;
          }
          // Skip retry for 404 — endpoint doesn't exist
          if (error instanceof HttpError && error.status === 404) {
            return;
          }
          if (retryCount >= 3) return;
          setTimeout(() => void revalidate({ retryCount }), 1500 * (retryCount + 1));
        },
      }}
    >
      {children}
    </SWRConfig>
  );
}
