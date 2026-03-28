/**
 * TUYUL FX Wolf-15 — Runtime Health Helper
 *
 * Quick snapshot of critical env config state.
 * Used by DataStreamDiagnostic to show operators whether
 * API_BASE, API_KEY, and WS_BASE are actually resolved.
 */

export interface RuntimeHealth {
    apiBaseResolved: boolean;
    /** Auth is session-based (JWT via HttpOnly cookie). Always true post-v3. */
    authSessionMode: boolean;
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
        // Auth is now session-based (login → JWT → HttpOnly cookie).
        // NEXT_PUBLIC_API_KEY is deprecated and must NOT be set (XSS risk).
        authSessionMode: true,
        wsBaseResolved: !!(process.env.NEXT_PUBLIC_WS_BASE_URL),
        nodeEnv: process.env.NODE_ENV ?? "unknown",
    };
}
