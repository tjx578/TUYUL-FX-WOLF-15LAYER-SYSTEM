"use client";

import { useMemo, useState } from "react";
import type { SignalViewModel } from "../model/signal.types";

export function useSignalSelection(signals: SignalViewModel[]) {
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [optimisticMap, setOptimisticMap] = useState<Record<string, "IDLE" | "SUBMITTING" | "SUBMITTED">>({});

    const enrichedSignals = useMemo(
        () =>
            signals.map((s) => ({
                ...s,
                optimisticTakeStatus: optimisticMap[s.id] ?? "IDLE",
            })),
        [signals, optimisticMap],
    );

    const selectedSignal = useMemo(
        () => enrichedSignals.find((s) => s.id === selectedId) ?? null,
        [enrichedSignals, selectedId],
    );

    return {
        selectedId,
        setSelectedId,
        selectedSignal,
        enrichedSignals,
        setOptimisticStatus: (signalId: string, status: "IDLE" | "SUBMITTING" | "SUBMITTED") =>
            setOptimisticMap((prev) => ({ ...prev, [signalId]: status })),
    };
}
