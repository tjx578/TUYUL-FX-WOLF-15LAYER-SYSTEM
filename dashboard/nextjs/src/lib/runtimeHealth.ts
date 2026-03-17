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
    // CRITICAL: Next.js statically inlines NEXT_PUBLIC_ env vars ONLY when the
    // full identifier appears as a direct expression — not via intermediate vars.
    // `const x = process.env.NEXT_PUBLIC_FOO; x` → x is undefined in browser.
    // `!!(process.env.NEXT_PUBLIC_FOO)` → correctly inlined at build time.
    return {
        apiBaseResolved: !!(process.env.NEXT_PUBLIC_API_BASE_URL),
        apiKeyPresent:   !!(process.env.NEXT_PUBLIC_API_KEY),
        wsBaseResolved:  !!(process.env.NEXT_PUBLIC_WS_BASE_URL),
        nodeEnv: process.env.NODE_ENV ?? "unknown",
    };
}
