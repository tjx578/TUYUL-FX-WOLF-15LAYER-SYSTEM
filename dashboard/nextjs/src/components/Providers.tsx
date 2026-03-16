"use client";

// ============================================================
// TUYUL FX Wolf-15 — Client Providers (SWR, etc.)
// Smart retry policy: skip 401/403 (auth errors are not transient),
// retry network/server errors up to 3 times with 1.5s delay.
// ============================================================

import { SWRConfig } from "swr";
import type { HttpError } from "@/lib/fetcher";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig
      value={{
        revalidateOnFocus: false,
        revalidateOnReconnect: true,
        shouldRetryOnError: true,
        errorRetryCount: 3,
        onErrorRetry: (error, _key, _config, revalidate, { retryCount }) => {
          const status = (error as HttpError)?.status;

          // Auth errors are not transient — don't spam the backend.
          if (status === 401 || status === 403) return;

          // 404 is usually a routing problem, not a transient error.
          if (status === 404) return;

          if (retryCount >= 3) return;

          setTimeout(() => {
            revalidate({ retryCount });
          }, 1500);
        },
      }}
    >
      {children}
    </SWRConfig>
  );
}
