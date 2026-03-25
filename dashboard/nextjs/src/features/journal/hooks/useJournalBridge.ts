"use client";

import { useSearchParams } from "next/navigation";
import { useMemo } from "react";

export interface JournalBridgeContext {
    accountId: string | null;
    signalId: string | null;
    hasBridgeContext: boolean;
}

export function useJournalBridge(): JournalBridgeContext {
    const searchParams = useSearchParams();

    return useMemo(() => {
        const accountId = searchParams.get("accountId");
        const signalId = searchParams.get("signalId");

        return {
            accountId,
            signalId,
            hasBridgeContext: !!(accountId || signalId),
        };
    }, [searchParams]);
}
