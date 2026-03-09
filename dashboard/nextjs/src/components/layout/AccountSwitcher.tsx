"use client";

import { useMemo } from "react";
import { useAccountStore } from "@/store/useAccountStore";

export default function AccountSwitcher() {
  const trades = useAccountStore((s) => s.trades);
  const label = useMemo(() => {
    const first = Object.values(trades)[0];
    return first?.account_id ?? "DEFAULT";
  }, [trades]);

  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/60 px-3 py-2 text-xs text-slate-300">
      Account: <span className="font-semibold text-white">{label}</span>
    </div>
  );
}
