import { useAllVerdicts } from "@/features/signals/api/verdicts.api";
import { useStatus } from "@/shared/api/system.api";

const _rawRefreshMs = parseInt(process.env.NEXT_PUBLIC_SIGNAL_REFRESH_INTERVAL_MS ?? "", 10);
const SIGNAL_REFRESH_INTERVAL_MS =
    Number.isFinite(_rawRefreshMs) && _rawRefreshMs > 0 ? _rawRefreshMs : 30_000;

export function useSignalsBootstrap() {
    const verdicts = useAllVerdicts({ refreshInterval: SIGNAL_REFRESH_INTERVAL_MS });
    const health = useStatus();

    return {
        verdicts,
        health,
    };
}
