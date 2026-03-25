"use client";

import { useMemo, useState } from "react";

export interface JournalFilterState {
    accountId: string;
    signalId: string;
    setAccountId: (value: string) => void;
    setSignalId: (value: string) => void;
}

export function useJournalFilters(initial?: {
    accountId?: string | null;
    signalId?: string | null;
}): JournalFilterState {
    const [accountId, setAccountId] = useState(initial?.accountId ?? "");
    const [signalId, setSignalId] = useState(initial?.signalId ?? "");

    return useMemo(
        () => ({
            accountId,
            signalId,
            setAccountId,
            setSignalId,
        }),
        [accountId, signalId],
    );
}
