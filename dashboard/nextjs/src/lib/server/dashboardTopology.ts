import { VIEWER_PROXY_PATHS } from "@/lib/viewerContract";

/** The core origin is server-only. Missing or invalid configuration fails closed. */
export function getCoreApiUrl(): string | null {
  const raw = process.env.INTERNAL_API_URL;
  if (!raw || raw !== raw.trim() || raw.length > 512 || /[\\\s,%?#]/.test(raw)) return null;
  try {
    const parsed = new URL(raw);
    if (!/^https?:\/\/[^/]+\/?$/i.test(raw) || parsed.username || parsed.password ||
        parsed.hostname.includes("*") || ["0.0.0.0", "[::]"].includes(parsed.hostname)) return null;
    const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname);
    if (parsed.protocol !== "https:" && (process.env.NODE_ENV === "production" || !loopback)) return null;
    const canonical = process.env.DASHBOARD_CANONICAL_ORIGIN;
    if (canonical && parsed.origin === new URL(canonical).origin) return null;
    return parsed.origin;
  } catch {
    return null;
  }
}

export interface UpstreamResult {
  url: string;
  surface: "core-api";
}

export function resolveDashboardUpstream(
  targetPath: string,
): UpstreamResult | null {
  if (!VIEWER_PROXY_PATHS.includes(targetPath)) return null;
  const coreUrl = getCoreApiUrl();
  return coreUrl ? { url: coreUrl, surface: "core-api" } : null;
}

export function resolveOperatorStatusSurface(): UpstreamResult | null {
  const coreUrl = getCoreApiUrl();
  return coreUrl ? { url: coreUrl, surface: "core-api" } : null;
}
