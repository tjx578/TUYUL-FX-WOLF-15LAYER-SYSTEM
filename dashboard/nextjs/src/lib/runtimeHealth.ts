/**
 * TUYUL FX Wolf-15 — Runtime Health Helper
 *
 * Quick snapshot of critical env config state.
 * Used by DataStreamDiagnostic to show operators whether
 * API_BASE, API_KEY, and WS_BASE are actually resolved.
 */

export interface RuntimeHealth {
    apiBaseResolved: boolean;
    apiKeyPresent: boolean;
    wsBaseResolved: boolean;
    nodeEnv: string;
}

export function getRuntimeHealth(): RuntimeHealth {
    const apiBase =
        process.env.NEXT_PUBLIC_API_BASE_URL?.trim() ||
        process.env.INTERNAL_API_URL?.trim() ||
        "";

    const apiKeyPresent = Boolean(process.env.NEXT_PUBLIC_API_KEY?.trim());

    const wsBase = process.env.NEXT_PUBLIC_WS_BASE_URL?.trim() || "";

    return {
        apiBaseResolved: Boolean(apiBase),
        apiKeyPresent,
        wsBaseResolved: Boolean(wsBase),
        nodeEnv: process.env.NODE_ENV ?? "unknown",
    };
}
