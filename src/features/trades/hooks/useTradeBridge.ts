"use client";

import { useMemo } from "react";
import { useLifecycleNavigationContext } from "@/shared/hooks/useLifecycleNavigationContext";
import type { TakeSignalBridgeContext } from "../model/trade.types";

export function useTradeBridge(): TakeSignalBridgeContext {
    const ctx = useLifecycleNavigationContext();

    return useMemo(() => {
        return {
            takeId: ctx?.takeId ?? null,
            accountId: ctx?.accountId ?? null,
            signalId: ctx?.signalId ?? null,
            hasBridgeContext: !!ctx,
        };
    }, [ctx]);
}
