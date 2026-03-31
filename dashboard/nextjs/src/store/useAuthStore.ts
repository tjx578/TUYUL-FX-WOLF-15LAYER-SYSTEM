import { create } from "zustand";
import type { SessionUser } from "@/contracts/auth";
import type { AuthoritySurface } from "@/contracts/authority";

// ── Authority cache entry ──────────────────────────────────────
interface CachedAuthorityEntry {
  value: AuthoritySurface;
  fetchedAt: number;
}

export const AUTHORITY_TTL_MS = 30_000;

// ── Consolidated auth + session + authority store ──────────────
interface AuthStore {
  // Auth
  user: SessionUser | null;
  loading: boolean;
  setUser: (user: SessionUser | null) => void;
  setLoading: (loading: boolean) => void;

  // Session (merged from useSessionStore)
  expiringInSeconds: number | null;
  expiredReason: string | null;
  refreshInFlight: boolean;
  setExpiringInSeconds: (value: number | null) => void;
  setExpiredReason: (reason: string | null) => void;
  setRefreshInFlight: (value: boolean) => void;

  // Authority cache (merged from useAuthorityStore)
  authorityCache: Record<string, CachedAuthorityEntry>;
  setAuthorityEntry: (key: string, value: AuthoritySurface) => void;
  invalidateAuthority: (key: string) => void;
  invalidateAuthorityPrefix: (prefix: string) => void;
  clearAuthorityCache: () => void;

  clear: () => void;
}

export const useAuthStore = create<AuthStore>((set) => ({
  // Auth
  user: null,
  loading: true,
  setUser: (user) => set({ user }),
  setLoading: (loading) => set({ loading }),

  // Session
  expiringInSeconds: null,
  expiredReason: null,
  refreshInFlight: false,
  setExpiringInSeconds: (value) => set({ expiringInSeconds: value }),
  setExpiredReason: (reason) => set({ expiredReason: reason }),
  setRefreshInFlight: (value) => set({ refreshInFlight: value }),

  // Authority cache
  authorityCache: {},
  setAuthorityEntry: (key, value) =>
    set((state) => ({
      authorityCache: {
        ...state.authorityCache,
        [key]: { value, fetchedAt: Date.now() },
      },
    })),
  invalidateAuthority: (key) =>
    set((state) => {
      const next = { ...state.authorityCache };
      delete next[key];
      return { authorityCache: next };
    }),
  invalidateAuthorityPrefix: (prefix) =>
    set((state) => {
      const next = { ...state.authorityCache };
      for (const k of Object.keys(next)) {
        if (k.startsWith(prefix)) {
          delete next[k];
        }
      }
      return { authorityCache: next };
    }),
  clearAuthorityCache: () => set({ authorityCache: {} }),

  // Clear all
  clear: () =>
    set({
      user: null,
      loading: false,
      expiringInSeconds: null,
      expiredReason: null,
      refreshInFlight: false,
      authorityCache: {},
    }),
}));
