/**
 * Shared API client primitives for the Wolf-15 dashboard.
 *
 * Every domain-specific API module (accounts, signals, trades, …) imports
 * `fetcher`, `apiMutate`, `apiMutateWithHeaders`, and `useApiQuery` from
 * here instead of defining their own fetch helpers.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { bearerHeader } from "@/lib/auth";
import { getRestPrefix } from "@/lib/env";
import { HttpError } from "@/lib/fetcher";
import { useSessionStore } from "@/store/useSessionStore";

// Resolved at module load: "" on local dev / valid build, "/api/proxy" on
// deployed hosts where build-time rewrites may be stale (Finding 3.1 fix).
const API_BASE = getRestPrefix();

// Global 429 cooldown — prevents all hooks from hammering a rate-limited backend.
let _rateLimitedUntil = 0;

export const POLL_INTERVALS = {
    context: 30_000,
    verdicts: 30_000,
    trades: 45_000,
    accounts: 45_000,
    execution: 60_000,
    risk: 60_000,
    orchestrator: 90_000,
    calendar: 120_000,
} as const;

export const API_ENDPOINTS = {
    health: "/healthz",
    orchestratorState: "/api/v1/orchestrator/state",
    accounts: "/api/v1/accounts",
    accountsRiskSnapshot: "/api/v1/accounts/risk-snapshot",
    accountsCapitalDeployment: "/api/v1/accounts/capital-deployment",
    tradesActive: "/api/v1/trades/active",
    tradesTake: "/api/v1/trades/take",
    tradesSkip: "/api/v1/trades/skip",
    tradesConfirmById: (tradeId: string) => `/api/v1/trades/${tradeId}/confirm`,
    tradesClose: "/api/v1/trades/close",
    riskSnapshotByAccount: (accountId: string) => `/api/v1/risk/${accountId}/snapshot`,
    riskPreviewMulti: "/api/v1/risk/preview-multi",
    verdictAll: "/api/v1/verdict/all",
    context: "/api/v1/context",
    execution: "/api/v1/execution",
    calendar: "/api/v1/calendar",
    calendarUpcoming: "/api/v1/calendar/upcoming",
    calendarBlocker: "/api/v1/calendar/blocker",
    calendarHealth: "/api/v1/calendar/health",
    /** @deprecated Use AGENT_MANAGER_ENDPOINTS from @/lib/agent-manager-api */
    eaStatus: "/api/v1/ea/status",
    /** @deprecated */
    eaLogs: "/api/v1/ea/logs",
    /** @deprecated */
    eaAgents: "/api/v1/ea/agents",
    /** @deprecated */
    eaRestart: "/api/v1/ea/restart",
    /** @deprecated */
    eaSafeMode: "/api/v1/ea/safe-mode",
    eaPing: "/api/v1/ea/ping",
    propFirmStatus: (accountId: string) => `/api/v1/prop-firm/${accountId}/status`,
    propFirmPhase: (accountId: string) => `/api/v1/prop-firm/${accountId}/phase`,
    configProfile: "/api/v1/config/profile",
    configProfileByName: (profileName: string) => `/api/v1/config/profile/${profileName}`,
    configActive: "/api/v1/config/profile/active",
    configEffective: "/api/v1/config/profile/effective",
    configOverrides: "/api/v1/config/profile/overrides",
    configOverrideLegacy: "/api/v1/config/profile/override",
    configLock: "/api/v1/config/profile/lock",
    configProfilesLegacy: "/api/v1/config/profiles",
} as const;

export const fetcher = async (url: string) => {
    if (useSessionStore.getState().expiredReason) {
        throw new HttpError("Session expired", 401);
    }

    if (_rateLimitedUntil > Date.now()) {
        throw new HttpError("Rate limited — waiting for cooldown", 429);
    }

    const auth = bearerHeader();
    const res = await fetch(`${API_BASE}${url}`, {
        credentials: "include",
        headers: {
            ...(auth ? { Authorization: auth } : {}),
        },
    });

    if (res.status === 429) {
        const retryAfter = res.headers.get("Retry-After");
        const retryMs = retryAfter ? parseInt(retryAfter, 10) * 1000 : 60_000;
        _rateLimitedUntil = Date.now() + retryMs;
        const err = new HttpError("Rate limited", 429);
        err.retryAfterMs = retryMs;
        throw err;
    }

    if (!res.ok) {
        let info: unknown = null;
        try {
            info = await res.json();
        } catch {
            try {
                info = await res.text();
            } catch {
                info = null;
            }
        }
        throw new HttpError(
            `Request failed: ${res.status} ${res.statusText}`,
            res.status,
            info
        );
    }

    return res.json();
};

export const apiMutate = async (url: string, body?: unknown, method = "POST") => {
    return apiMutateWithHeaders(url, body, method);
};

export const apiMutateWithHeaders = async (
    url: string,
    body?: unknown,
    method = "POST",
    headers?: Record<string, string>
) => {
    const governanceHeaders: Record<string, string> =
        method.toUpperCase() === "GET"
            ? {}
            : {
                "X-Edit-Mode": "ON",
                "X-Action-Reason": "UI_WRITE_ACTION",
                ...(process.env.NEXT_PUBLIC_ACTION_PIN
                    ? { "X-Action-Pin": process.env.NEXT_PUBLIC_ACTION_PIN }
                    : {}),
            };

    const auth = bearerHeader();
    const res = await fetch(`${API_BASE}${url}`, {
        method,
        credentials: "include",
        headers: {
            "Content-Type": "application/json",
            ...(auth ? { Authorization: auth } : {}),
            ...governanceHeaders,
            ...(headers ?? {}),
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
    });

    if (!res.ok) {
        let info: unknown = null;
        try {
            info = await res.json();
        } catch {
            try {
                info = await res.text();
            } catch {
                info = null;
            }
        }
        throw new HttpError(
            `Request failed: ${res.status} ${res.statusText}`,
            res.status,
            info
        );
    }

    return res.json().catch(() => undefined);
};

/**
 * Wrapper around @tanstack/react-query's useQuery that keeps return shape
 * consistent across all query hooks. `mutate()` invalidates the query key.
 */
export function useApiQuery<T>(
    key: string | null,
    opts?: { refetchInterval?: number },
) {
    const queryClient = useQueryClient();
    const { data, error, isLoading } = useQuery<T>({
        queryKey: [key],
        queryFn: () => fetcher(key!),
        enabled: !!key,
        ...(opts?.refetchInterval
            ? {
                refetchInterval: () => {
                    const remaining = _rateLimitedUntil - Date.now();
                    if (remaining > 0) return remaining + 1_000;
                    return opts.refetchInterval!;
                },
            }
            : {}),
    });
    const mutate = () => queryClient.invalidateQueries({ queryKey: [key] });
    return { data, isLoading, isError: !!error, error, mutate };
}
