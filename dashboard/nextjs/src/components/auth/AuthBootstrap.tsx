"use client";

import { useEffect } from "react";
import type { SessionUser } from "@/contracts/auth";
import { useAuthStore } from "@/store/useAuthStore";
import { scheduleRefresh, cancelRefresh } from "@/lib/auth";

interface AuthBootstrapProps {
  user: SessionUser;
}

export default function AuthBootstrap({ user }: AuthBootstrapProps) {
  const setUser = useAuthStore((state) => state.setUser);
  const setLoading = useAuthStore((state) => state.setLoading);

  useEffect(() => {
    setUser(user);
    setLoading(false);
  }, [user, setLoading, setUser]);

  // Resume JWT auto-refresh timer from existing token
  useEffect(() => {
    scheduleRefresh();
    return () => cancelRefresh();
  }, []);

  return null;
}
