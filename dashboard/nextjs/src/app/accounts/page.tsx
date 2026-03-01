"use client";

import React from "react";

import type { Account } from "@/types/account";
import { useAccounts } from "@/lib/api";

export default function AccountsPage() {
  const { data: accounts, isLoading, isError } = useAccounts();

  if (isLoading) {
    return <div>Loading accounts...</div>;
  }

  if (isError) {
    return <div>Failed to load accounts.</div>;
  }

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {accounts?.map((account: Account) => (
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
   