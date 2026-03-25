import type { SystemHealth, OrchestratorState, ContextSnapshot, ExecutionState } from "@/types";
import type { PipelineData } from "@/components/panels/PipelinePanel";
import { useApiQuery, API_ENDPOINTS, POLL_INTERVALS } from "@/shared/api/client";

export function useHealth() {
    const { data, error, isLoading } = useApiQuery<SystemHealth>(
        API_ENDPOINTS.health,
    );
    return { data, isLoading, isError: !!error, error };
}

export function useOrchestratorState() {
    const { data, error, isLoading, mutate } = useApiQuery<OrchestratorState>(
        API_ENDPOINTS.orchestratorState,
        { refetchInterval: POLL_INTERVALS.orchestrator },
    );
    return { data, isLoading, isError: !!error, error, mutate };
}

export function useContext() {
    const { data, error, isLoading } = useApiQuery<ContextSnapshot>(
        API_ENDPOINTS.context,
        { refetchInterval: POLL_INTERVALS.context },
    );
    return { data, isLoading, isError: !!error, error };
}

export function useExecution() {
    const { data, error, isLoading } = useApiQuery<ExecutionState>(
        API_ENDPOINTS.execution,
        { refetchInterval: POLL_INTERVALS.execution },
    );
    return { data, isLoading, isError: !!error, error };
}

export function usePipeline(pair: string) {
    const { data, error, isLoading } = useApiQuery<PipelineData>(
        pair ? `/api/v1/pipeline/${pair}` : null,
    );
    return { data, error, isLoading };
}
