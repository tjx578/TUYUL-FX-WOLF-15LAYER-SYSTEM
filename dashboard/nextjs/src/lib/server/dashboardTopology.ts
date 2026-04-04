/**
 * Dashboard Hybrid Topology — Upstream Resolver
 *
 * Determines whether a proxy request should route to the optional
 * dashboard-BFF or to core-api based on a code-defined allowlist.
 *
 * See docs/architecture/dashboard-hybrid-topology.md for the full contract.
 */

// ---------------------------------------------------------------------------
// Core-API URL (single-upstream baseline)
// ---------------------------------------------------------------------------

/**
 * Returns the core-api upstream URL, or `null` when unconfigured in
 * production.  The proxy MUST treat `null` as a misconfiguration and
 * return a 503.
 */
export function getCoreApiUrl(): string | null {
    const url =
        process.env.INTERNAL_API_URL ||
        process.env.NEXT_PUBLIC_API_BASE_URL ||
        null;

    if (url) return url.replace(/\/+$/, "");

    // In development / test, fall back to localhost so DX is frictionless.
    if (process.env.NODE_ENV !== "production") {
        return "http://localhost:8000";
    }

    return null;
}

// ---------------------------------------------------------------------------
// BFF allowlist (code-defined, NOT env-configurable)
// ---------------------------------------------------------------------------

/**
 * Path prefixes that are eligible for BFF routing.
 * Each entry is matched with `startsWith` against the proxy target path
 * (i.e. the path AFTER `/api/proxy/`).
 *
 * Exported for boundary testing only — do not import in runtime code
 * outside this module.
 */
export const BFF_ALLOWLISTED_PATHS: readonly string[] = Object.freeze([
    "dashboard/",
    "bff/",
]);

// ---------------------------------------------------------------------------
// BFF URL helper
// ---------------------------------------------------------------------------

function getBffUrl(): string | null {
    const url = process.env.INTERNAL_DASHBOARD_BFF_URL || null;
    if (!url) return null;
    return url.replace(/\/+$/, "");
}

// ---------------------------------------------------------------------------
// Upstream resolvers
// ---------------------------------------------------------------------------

export interface UpstreamResult {
    /** Fully-qualified upstream URL (no trailing slash). */
    url: string;
    /** Which surface this request resolved to. */
    surface: "core-api" | "bff";
}

/**
 * Resolve the upstream for a proxied REST request.
 *
 * @param targetPath — the path segment AFTER `/api/proxy/`
 *                     (e.g. `"dashboard/portfolio"` or `"v1/status"`).
 * @returns `UpstreamResult` or `null` when the resolved upstream is
 *          unconfigured (misconfiguration).
 */
export function resolveDashboardUpstream(
    targetPath: string,
): UpstreamResult | null {
    const bffUrl = getBffUrl();

    if (bffUrl && BFF_ALLOWLISTED_PATHS.some((p) => targetPath.startsWith(p))) {
        return { url: bffUrl, surface: "bff" };
    }

    const coreUrl = getCoreApiUrl();
    if (!coreUrl) return null;

    return { url: coreUrl, surface: "core-api" };
}

/**
 * Resolve the upstream for the operator status endpoint.
 *
 * Status always routes to core-api in Phase 1.
 */
export function resolveOperatorStatusSurface(): UpstreamResult | null {
    const coreUrl = getCoreApiUrl();
    if (!coreUrl) return null;

    return { url: coreUrl, surface: "core-api" };
}
