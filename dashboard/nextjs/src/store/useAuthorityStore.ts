import { create } from "zustand";
import type { AuthoritySurface } from "@/contracts/authority";

interface CachedAuthorityEntry {
  value: AuthoritySurface;
  fetchedAt: number;
}

interface AuthorityStore {
  cache: Record<string, CachedAuthorityEntry>;
  setEntry: (key: string, value: AuthoritySurface) => void;
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
  clear: () => set({ cache: {} }),
}));
