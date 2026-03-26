"use client";

import { useMemo } from "react";
import { useLifecycleNavigationContext } from "@/shared/hooks/useLifecycleNavigationContext";
import type { JournalFocusContract } from "../model/journal.types";

export function useJournalFocusContract(): JournalFocusContract | null {
  const ctx = useLifecycleNavigationContext();

  return useMemo(() => {
    if (!ctx) return null;

    return {
      accountId: ctx.accountId,
      signalId: ctx.signalId,
      takeId: ctx.takeId,
      source: ctx.sourcePage,
      filterMode: "contextual",
    };
  }, [ctx]);
}
