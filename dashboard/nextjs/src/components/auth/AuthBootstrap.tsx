"use client";

import { useEffect } from "react";
import type { SessionUser } from "@/contracts/auth";
import { useAuthStore } from "@/store/useAuthStore";
import { useSessionStore } from "@/store/useSessionStore";
import { scheduleRefresh, cancelRefresh } from "@/lib/auth";

interface AuthBootstrapProps {
  user: SessionUser;
}

export default function AuthBootstrap({ user }: AuthBootstrapProps) {
  const setUser = useAuthStore((state) => state.setUser);
  const setLoading = useAuthStore((state) => state.setLoading);
  const setExpiredReason = useSessionStore((state) => state.setExpiredReason);

  useEffect(() => {
    setUser(user);
    // Clear stale session expiry state when fresh user is loaded
    setExpiredReason(null);
    setLoading(false);
  }, [user, setExpiredReason, setLoading, setUser]);

  // Resume JWT auto-refresh timer from existing token
  useEffect(() => {
    scheduleRefresh();
    return () => cancelRefresh();
  }, []);

  return null;
}
