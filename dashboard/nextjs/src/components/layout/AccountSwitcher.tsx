"use client";

import { useAccounts } from "@/features/accounts/api/accounts.api";

export default function AccountSwitcher() {
  const { data: accounts } = useAccounts();
  const label = accounts.length > 0 ? accounts[0].account_name ?? accounts[0].account_id : "DEFAULT";

  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/60 px-3 py-2 text-xs text-slate-300">
      Account: <span className="font-semibold text-white">{label}</span>
    </div>
  );
}
