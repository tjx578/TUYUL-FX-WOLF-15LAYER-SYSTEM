"use client";

interface Props {
    accountId: string | null;
    signalId: string | null;
}

export function JournalBridgeBanner({ accountId, signalId }: Props) {
    return (
        <div
            style={{
                padding: 12,
                borderRadius: 10,
                border: "1px solid rgba(124,92,255,0.18)",
                background: "rgba(124,92,255,0.06)",
                fontSize: 13,
            }}
        >
            Viewing journal in lifecycle context
            {accountId ? ` \u2022 accountId=${accountId}` : ""}
            {signalId ? ` \u2022 signalId=${signalId}` : ""}
        </div>
    );
}
