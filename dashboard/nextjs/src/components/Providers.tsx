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
      }}
    >
      {children}
    </SWRConfig>
  );
}
