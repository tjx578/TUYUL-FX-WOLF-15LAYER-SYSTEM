"use client";

import { useMemo } from "react";
import type { SignalBoardState } from "../model/signal.types";
import { mapVerdictToSignalViewModel } from "../model/signal.mapper";
import { useSignalsBootstrap } from "../api/signals.api";
import { useSignalRealtime } from "./useSignalRealtime";

export function useSignalBoardData(): SignalBoardState {
    const { verdicts, health } = useSignalsBootstrap();

    const initialVerdicts = verdicts.data ?? [];
    const freshnessClass = health.data?.freshness_class;

    const live = useSignalRealtime(initialVerdicts, true);

    const mappedSignals = useMemo(() => {
        return (live.verdicts ?? []).map((v) =>
            mapVerdictToSignalViewModel(v, freshnessClass),
        );
    }, [live.verdicts, freshnessClass]);

    return {
        signals: mappedSignals,
        isLoading: verdicts.isLoading,
        isError: verdicts.isError,
        error: verdicts.error,
        wsStatus: live.status,
        isStale: live.isStale,
        lastUpdatedAt: live.lastUpdatedAt,
        freshnessClass,
    };
}
