"use client";

import type { AccountFocusContract } from "../model/account.types";

interface Props {
    focus: AccountFocusContract | null;
}

export function AccountsBridgeBanner({ focus }: Props) {
    if (!focus) return null;

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
            Highlighting account from {focus.source} lifecycle
            {focus.accountId ? ` \u2022 accountId=${focus.accountId}` : ""}
            {focus.signalId ? ` \u2022 signalId=${focus.signalId}` : ""}
            {focus.takeId ? ` \u2022 takeId=${focus.takeId}` : ""}
        </div>
    );
}
