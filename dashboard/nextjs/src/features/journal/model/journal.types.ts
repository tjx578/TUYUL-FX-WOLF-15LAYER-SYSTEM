export interface JournalFocusContract {
    accountId?: string | null;
    signalId?: string | null;
    takeId?: string | null;
    source: "signals" | "trades" | "manual";
    filterMode: "contextual" | "all";
}
