export interface AccountFocusContract {
    accountId: string;
    signalId?: string | null;
    takeId?: string | null;
    source: "signals" | "trades" | "manual";
    highlighted: boolean;
}
