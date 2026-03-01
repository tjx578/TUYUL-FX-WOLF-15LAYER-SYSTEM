"use client";

import React from "react";
import { useAccounts } from "@/lib/api";
import type { Account } from "@/types/account";

export default function AccountsPage() {
	const { data, isLoading, isError } = useAccounts();

	if (isLoading) {
		return <div>Loading accounts...</div>;
	}

	if (isError) {
		return <div>Failed to load accounts.</div>;
	}

	return (
		<div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
			{data?.map((a: Account) => (
				<div key={a.account_id} className="rounded-xl border p-4">
					<div className="font-semibold">{a.name}</div>
					<div className="text-sm opacity-80">{a.account_id}</div>
					<div className="mt-2">Balance: {a.balance}</div>
					<div>Equity: {a.equity}</div>
					<div className="text-xs mt-2">
						Prop Firm: {a.prop_firm ?? "-"}
					</div>
				</div>
			))}
		</div>
	);
}
   