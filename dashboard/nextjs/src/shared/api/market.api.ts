import type { PairInfo, PriceData, ProbabilitySummary, ProbabilityCalibration } from "@/types";
import { useApiQuery } from "@/shared/api/client";

export function usePricesREST() {
    const { data, error, isLoading, mutate } = useApiQuery<PriceData[]>(
        "/api/v1/prices",
    );
    return { data, isLoading, isError: !!error, error, mutate };
}

export function usePairs() {
    const { data, error, isLoading } = useApiQuery<PairInfo[]>(
        "/api/v1/pairs",
    );
    return { data, isLoading, isError: !!error, error };
}

export function useProbabilitySummary() {
    const { data, error, isLoading } = useApiQuery<ProbabilitySummary>(
        "/api/v1/probability/summary",
    );
    return { data, isLoading, isError: !!error, error };
}

export function useProbabilityCalibration() {
    const { data, error, isLoading } = useApiQuery<ProbabilityCalibration>(
        "/api/v1/probability/calibration",
    );
    return { data, isLoading, isError: !!error, error };
}
