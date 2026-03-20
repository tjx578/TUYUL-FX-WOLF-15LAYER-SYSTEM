"use client";

import { useActionThrottleStore } from "@/store/useActionThrottleStore";

export function useActionThrottle(key: string, minIntervalMs = 1_500) {
  const setTimestamp = useActionThrottleStore((s) => s.setTimestamp);
  const getTimestamp = useActionThrottleStore((s) => s.getTimestamp);

  const getRemainingMs = () => {
    const last = getTimestamp(key);
    if (!last) {
      return 0;
    }
    const elapsed = Date.now() - last;
    return Math.max(0, minIntervalMs - elapsed);
  };

  const isThrottled = () => getRemainingMs() > 0;

  const markNow = () => {
    setTimestamp(key, Date.now());
  };

  return {
    getRemainingMs,
    isThrottled,
    markNow,
  };
}