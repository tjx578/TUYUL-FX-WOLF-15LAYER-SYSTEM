"use client";

import { useAccounts } from "@/lib/api";

export default function AccountsPage() {
  const { data, isLoading } = useAccounts();

  if (isLoading) return <div>Loading accounts...</div>;

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {data?.map((a) => (
        <div key={a.account_id} className="rounded-xl border p-4">
          <div className="font-semibold">{a.name}</div>
          <div className="text-sm opacity-80">{a.account_id}</div>
          <div className="mt-2">Balance: {a.balance}</div>
          <div>Equity: {a.equity}</div>
          <div className="text-xs mt-2">Prop Firm: {a.prop_firm ?? "-"}</div>
        </div>
      ))}
    </div>
  );
}
