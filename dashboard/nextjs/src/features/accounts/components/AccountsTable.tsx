"use client";

interface AccountRow {
    accountId: string;
    accountName: string;
    broker: string;
    balance: number;
    equity: number;
    riskState?: string;
}

interface Props {
    accounts: AccountRow[];
    highlightedAccountId?: string | null;
}

export function AccountsTable({ accounts, highlightedAccountId }: Props) {
    return (
        <div style={{ display: "grid", gap: 8 }}>
            {accounts.map((account) => {
                const isHighlighted = highlightedAccountId === account.accountId;

                return (
                    <div
                        key={account.accountId}
                        style={{
                            padding: 12,
                            borderRadius: 8,
                            border: isHighlighted
                                ? "1px solid var(--accent, rgba(0,229,255,0.5))"
                                : "1px solid rgba(255,255,255,0.12)",
                            background: isHighlighted
                                ? "rgba(0,229,255,0.06)"
                                : "transparent",
                            display: "grid",
                            gridTemplateColumns: "1fr 1fr 1fr 1fr",
                            gap: 8,
                            fontSize: 13,
                        }}
                    >
                        <div>
                            <div style={{ opacity: 0.6, fontSize: 11 }}>Account</div>
                            <div>{account.accountName}</div>
                        </div>
                        <div>
                            <div style={{ opacity: 0.6, fontSize: 11 }}>Broker</div>
                            <div>{account.broker}</div>
                        </div>
                        <div>
                            <div style={{ opacity: 0.6, fontSize: 11 }}>Balance</div>
                            <div>{account.balance.toLocaleString()}</div>
                        </div>
                        <div>
                            <div style={{ opacity: 0.6, fontSize: 11 }}>Equity</div>
                            <div>{account.equity.toLocaleString()}</div>
                        </div>
                    </div>
                );
            })}
        </div>
    );
}
