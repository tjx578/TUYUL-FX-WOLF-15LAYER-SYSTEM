"use client";

import { useEffect, useMemo, useState } from "react";
import type { AuthoritySurface } from "@/contracts/authority";
import { fetchAuthoritySurface } from "@/services/authorityService";
import { buildAuthorityKey } from "@/lib/authorityKey";
import { AUTHORITY_TTL_MS, useAuthorityStore, type AuthorityStore } from "@/store/useAuthorityStore";

interface UseAuthoritySurfaceOptions {
    action: string;
    accountId?: string;
    tradeId?: string;
}

interface UseAuthoritySurfaceResult {
    authority: AuthoritySurface | null;
    loading: boolean;
    error: string | null;
    isCached: boolean;
    refresh: () => Promise<void>;
}

export function useAuthoritySurface(
    options: UseAuthoritySurfaceOptions
): UseAuthoritySurfaceResult {
    const key = useMemo(
        () => buildAuthorityKey(options.action, options.accountId, options.tradeId),
        [options.action, options.accountId, options.tradeId]
    );

    const cacheEntry = useAuthorityStore((state: AuthorityStore) => state.cache[key]);
    const setEntry = useAuthorityStore((state: AuthorityStore) => state.setEntry);

    const [authority, setAuthority] = useState<AuthoritySurface | null>(cacheEntry?.value ?? null);
    const [loading, setLoading] = useState(!cacheEntry);
    const [error, setError] = useState<string | null>(null);

    const isFresh = Boolean(cacheEntry) && Date.now() - cacheEntry.fetchedAt < AUTHORITY_TTL_MS;

    useEffect(() => {
        if (cacheEntry) {
            setAuthority(cacheEntry.value);
            setLoading(false);
        }
    }, [cacheEntry]);

    async function runFetch() {
        setLoading(true);
        setError(null);
        try {
            const next = await fetchAuthoritySurface(options.action, options.accountId, options.tradeId);
            setEntry(key, next);
            setAuthority(next);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to fetch authority surface");
        } finally {
            setLoading(false);
        }
    }

    useEffect(() => {
        if (!isFresh) {
            void runFetch();
        }
    }, [isFresh, key]);

    return {
        authority,
        loading,
        error,
        isCached: isFresh,
        refresh: runFetch,
    };
}
