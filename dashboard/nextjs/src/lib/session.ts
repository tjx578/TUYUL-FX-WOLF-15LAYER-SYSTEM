import { AUTH_SESSION } from "@/lib/endpoints";

export type CompatSessionUser = {
    user_id: string;
    email: string;
    role: string;
};

/**
 * Deterministic session probe — call backend /api/auth/session.
 *
 * Designed for Edge Runtime (Next.js middleware) where Node-only APIs
 * (like `next/headers`) are unavailable. Callers must forward the
 * raw cookie / authorization strings themselves.
 *
 * Returns a slim CompatSessionUser on success, null otherwise.
 */
export async function probeSession(
    cookie?: string,
    authorization?: string,
): Promise<CompatSessionUser | null> {
    const apiBase = (
        process.env.INTERNAL_API_URL ||
        process.env.NEXT_PUBLIC_API_URL ||
        process.env.NEXT_PUBLIC_API_BASE_URL ||
        ""
    ).replace(/\/$/, "");

    if (!apiBase.trim()) {
        return null;
    }

    const headers: Record<string, string> = {};
    if (authorization) headers["authorization"] = authorization;
    if (cookie) headers["cookie"] = cookie;

    try {
        const res = await fetch(`${apiBase}${AUTH_SESSION}`, {
            method: "GET",
            headers,
            cache: "no-store",
        });

        if (!res.ok) return null;

        const data: Record<string, unknown> = await res.json();
        return {
            user_id: String(data.user_id ?? data.sub ?? ""),
            email: String(data.email ?? ""),
            role: String(data.role ?? ""),
        };
    } catch {
        return null;
    }
}
