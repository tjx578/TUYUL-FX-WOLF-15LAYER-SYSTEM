"use client";

import { useMemo } from "react";

interface JournalEntryShape {
  entry_id: string;
  signal_id?: string;
  account_id?: string;
}

export function useJournalContextFilter<T extends JournalEntryShape>(
  entries: T[],
  focus: { accountId?: string | null; signalId?: string | null } | null,
) {
  return useMemo(() => {
    if (!focus?.accountId && !focus?.signalId) return entries;

    return entries.filter((entry) => {
      const accountOk = focus.accountId ? entry.account_id === focus.accountId : true;
      const signalOk = focus.signalId ? entry.signal_id === focus.signalId : true;
      return accountOk && signalOk;
    });
  }, [entries, focus?.accountId, focus?.signalId]);
}
