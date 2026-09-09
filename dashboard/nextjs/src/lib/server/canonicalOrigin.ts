/** Server configuration is the sole origin authority; forwarded headers are untrusted. */
export function normalizeBrowserOrigin(raw: string | null | undefined): string | null {
  if (!raw || raw.length > 512 || raw !== raw.trim() || /[\\\s,%?#]/.test(raw)) return null;
  try {
    const url = new URL(raw);
    if (!/^https?:\/\/[^/]+\/?$/i.test(raw) || url.username || url.password || url.pathname !== "/") return null;
    if (["0.0.0.0", "[::]"].includes(url.hostname) || url.hostname.includes("*")) return null;
    if (url.protocol !== "https:" && !(url.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname))) return null;
    return url.origin;
  } catch { return null; }
}

let diagnostics = 0;
export function checkCanonicalOrigin(request: { headers: Headers; nextUrl: { origin: string } }): 403 | 503 | null {
  const canonical = normalizeBrowserOrigin(process.env.DASHBOARD_CANONICAL_ORIGIN);
  const incoming = normalizeBrowserOrigin(request.headers.get("origin"));
  // Opt-in, non-production only, capped per process. Never log raw headers or credentials.
  if (process.env.NODE_ENV !== "production" && process.env.DASHBOARD_ORIGIN_DIAGNOSTICS === "1" && diagnostics++ < 5) {
    const safeHost = (value: string | null) => normalizeBrowserOrigin(value ? "https://" + value : null);
    console.info("dashboard-origin", {
      canonical, incoming, calculated: normalizeBrowserOrigin(request.nextUrl.origin),
      host: safeHost(request.headers.get("host")),
      forwardedHost: safeHost(request.headers.get("x-forwarded-host")),
      forwardedProto: ["http", "https"].includes(request.headers.get("x-forwarded-proto") ?? "") ? request.headers.get("x-forwarded-proto") : null,
    });
  }
  if (!canonical) return 503;
  return incoming === canonical ? null : 403;
}
