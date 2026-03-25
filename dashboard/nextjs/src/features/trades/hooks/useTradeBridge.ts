"use client";

import { useSearchParams } from "next/navigation";
import { useMemo } from "react";
import type { TakeSignalBridgeContext } from "../model/trade.types";

export function useTradeBridge(): TakeSignalBridgeContext {
    const searchParams = useSearchParams();

    return useMemo(() => {
        const takeId = searchParams.get("takeId");
        const accountId = searchParams.get("accountId");
        const signalId = searchParams.get("signalId");

        return {
            takeId,
            accountId,
            signalId,
            hasBridgeContext: !!(takeId || accountId || signalId),
        };
    }, [searchParams]);
}
