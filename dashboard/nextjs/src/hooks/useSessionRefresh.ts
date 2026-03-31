"use client";

import { useCallback } from "react";
import { refreshSession } from "@/services/sessionService";
import { useAuthStore } from "@/store/useAuthStore";

export function useSessionRefresh() {
  const setUser = useAuthStore((state) => state.setUser);
  const setExpiredReason = useAuthStore((state) => state.setExpiredReason);
  const setExpiringInSeconds = useAuthStore((state) => state.setExpiringInSeconds);
  const setRefreshInFlight = useAuthStore((state) => state.setRefreshInFlight);

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
