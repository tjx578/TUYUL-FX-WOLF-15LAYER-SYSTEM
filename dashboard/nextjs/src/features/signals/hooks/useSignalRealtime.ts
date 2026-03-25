import type { L12Verdict } from "@/types";
import { useLiveSignals } from "@/lib/realtime/hooks/useLiveSignals";

export function useSignalRealtime(initialVerdicts: L12Verdict[], enabled = true) {
    return useLiveSignals(initialVerdicts, enabled);
}
