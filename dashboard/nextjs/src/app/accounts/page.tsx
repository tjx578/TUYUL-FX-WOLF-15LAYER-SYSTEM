"use client";

import { useAccounts } from "@/lib/api";
import type { Account } from "@/types/account";

export default function AccountsPage() {
  const { data: accounts, isLoading } = useAccounts();
  const data: Account[] | undefined = accounts;

  if (isLoading) return <div>Loading accounts...</div>;

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {data?.map((account) => (
        <div key={account.account_id} className="rounded-xl border p-4">
          <div className="font-semibold">{account.name}</div>
          <div className="text-sm opacity-80">{account.account_id}</div>
          <div className="mt-2">Balance: {account.balance}</div>
          <div>Equity: {account.equity}</div>
          <div className="text-xs mt-2">Prop Firm: {account.prop_firm ?? "-"}</div>
        </div>
      ))}
    </div>
  );
}
