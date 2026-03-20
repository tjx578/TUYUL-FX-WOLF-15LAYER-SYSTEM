import { create } from "zustand";

interface SessionStore {
  expiringInSeconds: number | null;
  expiredReason: string | null;
  refreshInFlight: boolean;
  setExpiringInSeconds: (value: number | null) => void;
  setExpiredReason: (reason: string | null) => void;
  setRefreshInFlight: (value: boolean) => void;
  clear: () => void;
}

export const useSessionStore = create<SessionStore>((set) => ({
  expiringInSeconds: null,
  expiredReason: null,
  refreshInFlight: false,
  setExpiringInSeconds: (value) => set({ expiringInSeconds: value }),
  setExpiredReason: (reason) => set({ expiredReason: reason }),
  setRefreshInFlight: (value) => set({ refreshInFlight: value }),
  clear: () =>
    set({
      expiringInSeconds: null,
      expiredReason: null,
      refreshInFlight: false,
    }),
}));
