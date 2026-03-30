import type { SystemHealth, OrchestratorState, ContextSnapshot, ExecutionState } from "@/types";
import type { PipelineData } from "@/components/panels/PipelinePanel";
import { useApiQuery, API_ENDPOINTS, POLL_INTERVALS } from "@/shared/api/client";

export function useStatus() {
    const { data, error, isLoading } = useApiQuery<SystemHealth>(
        API_ENDPOINTS.status,
    );
    return { data, isLoading, isError: !!error, error };
}

/** @deprecated Use useStatus() — kept as alias for migration. */
export const useHealth = useStatus;

export function useOrchestratorState() {
    const { data, error, isLoading, mutate } = useApiQuery<OrchestratorState>(
        API_ENDPOINTS.orchestratorState,
        { refetchInterval: POLL_INTERVALS.orchestrator },
    );
    return { data, isLoading, isError: !!error, error, mutate };
}

export function useContext() {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { data: raw, error, isLoading } = useApiQuery<any>(
        API_ENDPOINTS.context,
        { refetchInterval: POLL_INTERVALS.context },
    );
    // Map nested backend response → flat ContextSnapshot for UI
    const data: ContextSnapshot | undefined = raw
        ? {
              session: raw.inference?.session_state?.session ?? "",
              regime:
                  raw.inference?.volatility_regime ??
                  raw.meta?.volatility_regime ??
                  "",
              volatility:
                  raw.inference?.volatility_regime ??
                  raw.meta?.volatility_regime ??
                  "",
              trend: "",
              active_pairs:
                  typeof raw.active_pairs === "number"
                      ? raw.active_pairs
                      : 0,
              timestamp: raw.inference?.inference_ts ?? 0,
          }
        : undefined;
    return { data, isLoading, isError: !!error, error };
}

export function useExecution() {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { data: raw, error, isLoading } = useApiQuery<any>(
        API_ENDPOINTS.execution,
        { refetchInterval: POLL_INTERVALS.execution },
    );
    // Aggregate per-symbol states → single top-level ExecutionState for UI
    const data: ExecutionState | undefined = raw
        ? (() => {
              const symbols = raw.symbols ?? {};
              const priorities: Record<string, number> = {
                  EXECUTING: 4,
                  SIGNAL_READY: 3,
                  SCANNING: 2,
                  COOLDOWN: 1,
                  IDLE: 0,
              };
              let topState: ExecutionState["state"] = "IDLE";
              let topPair: string | undefined;
              let topPri = -1;
              for (const [sym, info] of Object.entries(symbols)) {
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  const st = (info as any)?.state as string;
                  const pri = priorities[st] ?? 0;
                  if (pri > topPri) {
                      topPri = pri;
                      topState = st as ExecutionState["state"];
                      topPair = sym;
                  }
              }
              return {
                  state: topState,
                  current_pair: topPair,
                  signal_count: Object.keys(symbols).length,
              };
          })()
        : undefined;
    return { data, isLoading, isError: !!error, error };
}

export function usePipeline(pair: string) {
    const { data, error, isLoading } = useApiQuery<PipelineData>(
        pair ? `/api/v1/pipeline/${pair}` : null,
    );
    return { data, error, isLoading };
}
