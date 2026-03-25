"use client";

interface Props {
    accountId: string | null;
    signalId: string | null;
}

export function AccountsBridgeBanner({ accountId, signalId }: Props) {
    return (
        <div
            style={{
                padding: 12,
                borderRadius: 10,
                border: "1px solid rgba(0,230,118,0.18)",
                background: "rgba(0,230,118,0.06)",
                fontSize: 13,
            }}
        >
            Highlighting account used in signal lifecycle
            {accountId ? ` \u2022 accountId=${accountId}` : ""}
            {signalId ? ` \u2022 signalId=${signalId}` : ""}
        </div>
    );
}
