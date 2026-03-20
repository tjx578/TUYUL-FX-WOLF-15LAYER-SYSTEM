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
        // Guard: only fire once — skip if already marked expired.
        if (error instanceof HttpError && error.status === 401) {
          const session = useSessionStore.getState();
          if (!session.expiredReason) {
            useAuthStore.getState().clear();
            session.setExpiredReason("SESSION_EXPIRED");
          }
        }

        // Global 429 handler: record a cooldown window so retry() can honour it.
        if (error instanceof HttpError && error.status === 429) {
          _rateLimitedUntil = Date.now() + (error.retryAfterMs ?? 60_000);
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
