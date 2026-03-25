"use client";

import { useMemo, useState } from "react";
import type { SignalFilterMode, SignalViewModel } from "../model/signal.types";
import {
    isAbortVerdict,
    isExecuteVerdict,
    isHoldVerdict,
} from "../model/signal.constants";

export function useSignalBoardFilters(signals: SignalViewModel[]) {
    const [query, setQuery] = useState("");
    const [mode, setMode] = useState<SignalFilterMode>("ALL");

    const filteredSignals = useMemo(() => {
        const q = query.trim().toUpperCase();

        return signals
            .filter((s) => (q ? s.symbol.toUpperCase().includes(q) : true))
            .filter((s) => {
                if (mode === "ALL") return true;
                if (mode === "EXECUTE") return isExecuteVerdict(s.verdict);
                if (mode === "HOLD") return isHoldVerdict(s.verdict);
                if (mode === "ABORT") return isAbortVerdict(s.verdict);
                return true;
            })
            .sort((a, b) => {
                if (b.confidence !== a.confidence) return b.confidence - a.confidence;
                return b.timestamp - a.timestamp;
            });
    }, [signals, query, mode]);

    return {
        query,
        setQuery,
        mode,
        setMode,
        filteredSignals,
    };
}
