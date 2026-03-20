import { QueryClient, QueryCache } from "@tanstack/react-query";
import { HttpError } from "@/lib/fetcher";
import { useAuthStore } from "@/store/useAuthStore";
import { useSessionStore } from "@/store/useSessionStore";

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
            // 429 = rate limited — retrying only amplifies the problem
            if (error.status === 429) {
              return false;
            }
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
