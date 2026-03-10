"use client";

import { useCallback } from "react";
import { refreshSession } from "@/services/sessionService";
import { useSessionStore } from "@/store/useSessionStore";
import { useAuthStore } from "@/store/useAuthStore";

export function useSessionRefresh() {
  const setUser = useAuthStore((state) => state.setUser);
  const setExpiredReason = useSessionStore((state) => state.setExpiredReason);
  const setExpiringInSeconds = useSessionStore((state) => state.setExpiringInSeconds);
  const setRefreshInFlight = useSessionStore((state) => state.setRefreshInFlight);

  return useCallback(async () => {
    setRefreshInFlight(true);
    try {
      const user = await refreshSession();
      setUser(user);
      setExpiredReason(null);
      setExpiringInSeconds(null);
    } catch {
      setExpiredReason("SESSION_REFRESH_FAILED");
    } finally {
      setRefreshInFlight(false);
    }
  }, [setExpiredReason, setExpiringInSeconds, setRefreshInFlight, setUser]);
}
