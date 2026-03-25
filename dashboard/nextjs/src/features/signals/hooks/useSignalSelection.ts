"use client";

import { useMemo, useState } from "react";
import type { SignalViewModel } from "../model/signal.types";

export function useSignalSelection(signals: SignalViewModel[]) {
    const [selectedId, setSelectedId] = useState<string | null>(null);

    const selectedSignal = useMemo(
        () => signals.find((s) => s.id === selectedId) ?? null,
        [signals, selectedId],
    );

    return {
        selectedId,
        setSelectedId,
        selectedSignal,
    };
}
