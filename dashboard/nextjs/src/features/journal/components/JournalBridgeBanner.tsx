"use client";

import type { JournalFocusContract } from "../model/journal.types";

interface Props {
    focus: JournalFocusContract | null;
}

export function JournalBridgeBanner({ focus }: Props) {
    if (!focus) return null;

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
            Journal in {focus.filterMode} mode
            {focus.accountId ? ` \u2022 accountId=${focus.accountId}` : ""}
            {focus.signalId ? ` \u2022 signalId=${focus.signalId}` : ""}
            {focus.takeId ? ` \u2022 takeId=${focus.takeId}` : ""}
        </div>
    );
}
