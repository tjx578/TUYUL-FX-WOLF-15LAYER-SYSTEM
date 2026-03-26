import type { RiskSnapshot } from "@/types";
import { useApiQuery, API_ENDPOINTS, POLL_INTERVALS } from "@/shared/api/client";

export function useRiskSnapshot(accountId: string) {
    const { data, error, isLoading } = useApiQuery<RiskSnapshot>(
        accountId ? API_ENDPOINTS.riskSnapshotByAccount(accountId) : null,
        { refetchInterval: POLL_INTERVALS.risk },
    );
    return { data, isLoading, isError: !!error, error };
}
