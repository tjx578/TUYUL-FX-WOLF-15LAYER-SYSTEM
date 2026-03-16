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
    const publicApiBaseRaw = process.env.NEXT_PUBLIC_API_BASE_URL;
    const publicApiKeyRaw = process.env.NEXT_PUBLIC_API_KEY;
    const publicWsBaseRaw = process.env.NEXT_PUBLIC_WS_BASE_URL;

    const apiBase = typeof publicApiBaseRaw === "string" ? publicApiBaseRaw.trim() : "";
    const wsBase = typeof publicWsBaseRaw === "string" ? publicWsBaseRaw.trim() : "";
    const apiKeyPresent = typeof publicApiKeyRaw === "string" && publicApiKeyRaw.trim().length > 0;

    return {
        apiBaseResolved: apiBase.length > 0,
        apiKeyPresent,
        wsBaseResolved: wsBase.length > 0,
        nodeEnv: process.env.NODE_ENV ?? "unknown",
    };
}
