import { QueryClient, QueryCache } from "@tanstack/react-query";
import { HttpError } from "@/lib/fetcher";
import { useAuthStore } from "@/store/useAuthStore";
import { useSessionStore } from "@/store/useSessionStore";

// Global rate-limit cooldown: when a 429 is received, all queries pause until
// this timestamp passes.  Updated by the QueryCache onError handler.
let _rateLimitedUntil = 0;

export function createQueryClient() {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (error) => {
        // Global 401 handler: clear stale auth state and trigger session expiry.
        // Guard: only fire when a real user session existed.
        // In owner mode (user_id === "owner") the dashboard has no JWT —
        // a 401 means missing API_KEY configuration, not an expired session.
        if (error instanceof HttpError && error.status === 401) {
          const session = useSessionStore.getState();
          const auth = useAuthStore.getState();
          const hasRealSession = auth.user != null && auth.user.user_id !== "owner";
          if (hasRealSession && !session.expiredReason) {
            auth.clear();
            session.setExpiredReason("SESSION_EXPIRED");
          }
        }

        // Global 429 handler: record a cooldown window so retry() can honour it.
        // Guard: only set if not already active — during cooldown the fetcher
        // short-circuits with synthetic 429s that must NOT reset the timer
        // (otherwise cooldown extends infinitely and the dashboard never recovers).
        if (error instanceof HttpError && error.status === 429) {
          if (_rateLimitedUntil < Date.now()) {
            _rateLimitedUntil = Date.now() + (error.retryAfterMs ?? 60_000);
          }
        }
      },
    }),
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: false,
        refetchOnReconnect: true,
        retry: (failureCount, error) => {
          // Skip retry for auth/not-found errors — they are not transient
          if (error instanceof HttpError) {
            if (error.status === 401 || error.status === 403 || error.status === 404) {
              return false;
            }
            // 429 Too Many Requests — retrying only makes it worse
            if (error.status === 429) {
              return false;
            }
          }
          // Respect the global rate-limit cooldown window
          if (Date.now() < _rateLimitedUntil) {
            return false;
          }
          return failureCount < 3;
        },
      },
      mutations: {
        retry: false,
      },
    },
  });
}
