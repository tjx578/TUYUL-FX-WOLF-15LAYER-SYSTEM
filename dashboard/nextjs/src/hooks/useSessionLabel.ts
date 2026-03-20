"use client";

import { useState, useEffect } from "react";
import { sessionLabel } from "@/lib/timezone";

/**
 * Returns a live-updating trading session label (ASIA / LONDON / NEW_YORK / OFF_SESSION).
 * Recomputes every 10 seconds based on local time in configured timezone.
 */
export function useSessionLabel(): string {
  const [session, setSession] = useState(sessionLabel());

  useEffect(() => {
    const id = setInterval(() => setSession(sessionLabel()), 10_000);
    return () => clearInterval(id);
  }, []);

  return session;
}
