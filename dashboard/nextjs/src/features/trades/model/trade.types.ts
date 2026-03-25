export type TakeSignalLifecycleStatus =
    | "PENDING"
    | "FIREWALL_APPROVED"
    | "FIREWALL_REJECTED"
    | "EXECUTION_SENT"
    | "EXECUTED"
    | "REJECTED"
    | "CANCELLED"
    | "EXPIRED";

export interface TakeSignalBridgeContext {
    takeId: string | null;
    accountId: string | null;
    signalId: string | null;
    hasBridgeContext: boolean;
}

export interface TradeLifecycleBridgeViewModel {
    takeId: string;
    signalId?: string | null;
    accountId?: string | null;
    status: TakeSignalLifecycleStatus | "UNKNOWN";
    statusReason?: string | null;
    executionIntentId?: string | null;
    firewallResultId?: string | null;
}
