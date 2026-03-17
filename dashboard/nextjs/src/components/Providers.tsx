"use client";

// ============================================================
// TUYUL FX Wolf-15 — Client Providers
// Previously wrapped children in SWRConfig. All data-fetching now
// uses React Query exclusively — 401 handling and retry policy live
// in queryClient.ts (consumed by QueryProvider in root layout).
// This wrapper is kept for route-group layout compatibility.
// ============================================================

export function Providers({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
