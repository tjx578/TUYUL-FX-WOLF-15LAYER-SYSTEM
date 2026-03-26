import { useSyncExternalStore } from "react";
import type { AuthoritySurface } from "@/contracts/authority";

interface CachedAuthorityEntry {
    value: AuthoritySurface;
    fetchedAt: number;
}

export interface AuthorityStore {
    cache: Record<string, CachedAuthorityEntry>;
    setEntry: (key: string, value: AuthoritySurface) => void;
    invalidate: (key: string) => void;
    invalidatePrefix: (prefix: string) => void;
    clear: () => void;
}

export const AUTHORITY_TTL_MS = 30_000;

const listeners = new Set<() => void>();

let cacheState: Record<string, CachedAuthorityEntry> = {};

function emitChange(): void {
    for (const listener of listeners) {
        listener();
    }
}

function subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}

function getSnapshot(): AuthorityStore {
    return {
        cache: cacheState,
        setEntry: (key: string, value: AuthoritySurface) => {
            cacheState = {
                ...cacheState,
                [key]: {
                    value,
                    fetchedAt: Date.now(),
                },
            };
            emitChange();
        },
        invalidate: (key: string) => {
            const next = { ...cacheState };
            delete next[key];
            cacheState = next;
            emitChange();
        },
        invalidatePrefix: (prefix: string) => {
            const next = { ...cacheState };
            for (const key of Object.keys(next)) {
                if (key.startsWith(prefix)) {
                    delete next[key];
                }
            }
            cacheState = next;
            emitChange();
        },
        clear: () => {
            cacheState = {};
            emitChange();
        },
    };
}

export function useAuthorityStore<T>(selector: (state: AuthorityStore) => T): T {
    const snapshot = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
    return selector(snapshot);
}
