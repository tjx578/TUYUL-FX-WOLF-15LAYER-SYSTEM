import { NextRequest, NextResponse } from "next/server";
import { resolveOperatorStatusSurface } from "@/lib/server/dashboardTopology";

/**
 * GET /api/status
 *
 * Operator-level system status — rich diagnostics for the dashboard.
 * This is NOT an infra health probe. Infra probes (/healthz, /readyz)
 * are forwarded by the catch-all proxy to the backend and carry no auth.
 *
 * This route:
 *   - Requires a session cookie (owner auth)
 *   - Fetches /api/v1/status from the backend
 *   - Returns the operator diagnostics payload (SystemHealth)
 *
 * Semantic split:
 *   /healthz, /readyz  → infra liveness/readiness (no auth, no operator data)
 *   /api/status        → operator diagnostics (session-authed, rich payload)
 */

const SESSION_COOKIE = "wolf15_session";

export async function GET(request: NextRequest): Promise<NextResponse> {
    const sessionToken = request.cookies.get(SESSION_COOKIE)?.value?.trim();
    if (!sessionToken) {
        return NextResponse.json(
            { error: "Unauthorized — session required for operator status" },
            { status: 401 },
        );
    }

    const upstream = resolveOperatorStatusSurface();
    if (!upstream) {
        return NextResponse.json(
            {
                error: "Status endpoint misconfigured — backend URL not set",
                code: "STATUS_MISCONFIGURED",
            },
            {
                status: 503,
                headers: {
                    "x-status-source": "operator",
                    "x-status-surface": "unknown",
                },
            },
        );
    }

    const targetUrl = `${upstream.url}/api/v1/status`;

    try {
        const response = await fetch(targetUrl, {
            headers: {
                authorization: `Bearer ${sessionToken}`,
                accept: "application/json",
            },
        });

        const data = await response.json();

        return NextResponse.json(data, {
            status: response.status,
            headers: {
                "x-status-source": "operator",
                "x-status-surface": upstream.surface,
                "cache-control": "no-store",
            },
        });
    } catch (error) {
        return NextResponse.json(
            {
                error: "Backend unreachable",
                detail: error instanceof Error ? error.message : "Connection failed",
            },
            {
                status: 502,
                headers: {
                    "x-status-source": "operator",
                    "x-status-surface": upstream.surface,
                },
            },
        );
    }
}
