import { create } from "zustand";
import type { AuthoritySurface } from "@/contracts/authority";

interface CachedAuthorityEntry {
  value: AuthoritySurface;
  fetchedAt: number;
}

interface AuthorityStore {
  cache: Record<string, CachedAuthorityEntry>;
  setEntry: (key: string, value: AuthoritySurface) => void;
  invalidate: (key: string) => void;
  invalidatePrefix: (prefix: string) => void;
  clear: () => void;
}

export const AUTHORITY_TTL_MS = 30_000;

export const useAuthorityStore = create<AuthorityStore>((set) => ({
  cache: {},
  setEntry: (key, value) =>
    set((state) => ({
      cache: {
        ...state.cache,
        [key]: {
          value,
          fetchedAt: Date.now(),
        },
      },
    })),
  invalidate: (key) =>
    set((state) => {
      const next = { ...state.cache };
      delete next[key];
      return { cache: next };
    }),
  invalidatePrefix: (prefix) =>
    set((state) => {
      const next = { ...state.cache };
      for (const key of Object.keys(next)) {
        if (key.startsWith(prefix)) {
          delete next[key];
        }
      }
      return { cache: next };
    }),
  clear: () => set({ cache: {} }),
}));
