import type { QueryClient } from "@tanstack/react-query";
import { TAKE_SIGNAL_INVALIDATION_KEYS } from "./queryKeys";

export async function invalidateDashboardQueries(
    queryClient: QueryClient,
    keys: readonly string[],
): Promise<void> {
    await Promise.all(
        keys.map((key) =>
            queryClient.invalidateQueries({
                queryKey: [key],
            }),
        ),
    );
}

export async function invalidateAfterTakeSignal(
    queryClient: QueryClient,
): Promise<void> {
    await invalidateDashboardQueries(queryClient, TAKE_SIGNAL_INVALIDATION_KEYS);
}
