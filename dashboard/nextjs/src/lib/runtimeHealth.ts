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
    // IMPORTANT: NEXT_PUBLIC_ env vars must be accessed as literal identifiers —
    // NOT via optional chaining or dynamic lookup — so the Next.js compiler can
    // statically inline their values into the client bundle at build time.
    // Using process.env.SOME_VAR?.trim() causes the value to be undefined in the
    // browser even when the env var is correctly set on Vercel.
    const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || "";

    // INTERNAL_API_URL is server-side only (no NEXT_PUBLIC_ prefix) — it is never
    // available in the browser bundle. Do NOT reference it here.

    const apiKeyPresent = !!(process.env.NEXT_PUBLIC_API_KEY);

    const wsBase = process.env.NEXT_PUBLIC_WS_BASE_URL || "";

    return {
        apiBaseResolved: wsBase !== "" || apiBase !== "",
        apiKeyPresent,
        wsBaseResolved: wsBase !== "",
        nodeEnv: process.env.NODE_ENV ?? "unknown",
    };
}
