"use client";

import { useSearchParams } from "next/navigation";
import { useMemo } from "react";

export interface AccountsBridgeContext {
    accountId: string | null;
    signalId: string | null;
    hasBridgeContext: boolean;
}

export function useAccountsBridge(): AccountsBridgeContext {
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
