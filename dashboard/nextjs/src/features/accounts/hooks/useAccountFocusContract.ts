"use client";

import { useMemo } from "react";
import { useLifecycleNavigationContext } from "@/shared/hooks/useLifecycleNavigationContext";
import type { AccountFocusContract } from "../model/account.types";

export function useAccountFocusContract(): AccountFocusContract | null {
  const ctx = useLifecycleNavigationContext();

  return useMemo(() => {
    if (!ctx?.accountId) return null;

    return {
      accountId: ctx.accountId,
      signalId: ctx.signalId,
      takeId: ctx.takeId,
      source: ctx.sourcePage,
      highlighted: true,
    };
  }, [ctx]);
}
