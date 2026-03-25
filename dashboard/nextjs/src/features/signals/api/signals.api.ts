import { useAllVerdicts, useHealth } from "@/lib/api";

export function useSignalsBootstrap() {
    const verdicts = useAllVerdicts({ refreshInterval: 30_000 });
    const health = useHealth();

    return {
        verdicts,
        health,
    };
}
