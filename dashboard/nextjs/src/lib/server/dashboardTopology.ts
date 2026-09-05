/**
 * Runtime upstream selection for the isolated G4 viewer surface.
 *
 * Only the three paths in VIEWER_PROXY_PATHS can resolve to the dashboard BFF.
 * Missing BFF configuration fails closed; it never falls back to core.
 */

import { VIEWER_PROXY_PATHS } from "@/lib/viewerContract";

export function getCoreApiUrl(): string | null {
  const url =
    process.env.INTERNAL_API_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    null;

  if (url) return url.replace(/\/+$/, "");
  return process.env.NODE_ENV === "production" ? null : "http://localhost:8000";
}

export const BFF_ALLOWLISTED_PATHS: readonly string[] = VIEWER_PROXY_PATHS;

function getBffUrl(): string | null {
  const url = process.env.INTERNAL_DASHBOARD_BFF_URL || null;
  return url ? url.replace(/\/+$/, "") : null;
}

export interface UpstreamResult {
  url: string;
  surface: "core-api" | "bff";
}

export function resolveDashboardUpstream(
  targetPath: string,
): UpstreamResult | null {
  if (BFF_ALLOWLISTED_PATHS.includes(targetPath)) {
    const bffUrl = getBffUrl();
    return bffUrl ? { url: bffUrl, surface: "bff" } : null;
  }

  const coreUrl = getCoreApiUrl();
  return coreUrl ? { url: coreUrl, surface: "core-api" } : null;
}

export function resolveOperatorStatusSurface(): UpstreamResult | null {
  const coreUrl = getCoreApiUrl();
  return coreUrl ? { url: coreUrl, surface: "core-api" } : null;
}
