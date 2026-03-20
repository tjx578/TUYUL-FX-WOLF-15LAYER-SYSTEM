import type { FeedStatus } from "@/types";

export type VerdictEmptyReason =
    | "TRANSPORT_DEGRADED"
    | "VERDICT_STALE"
    | "NO_VERDICT_AVAILABLE";

export interface VerdictEmptyState {
    reason: VerdictEmptyReason;
    title: string;
    detail: string;
    badgeLabel: "TRANSPORT" | "STALE" | "NO_DATA";
    badgeClass: "badge badge-red" | "badge badge-gold" | "badge badge-muted";
}

interface VerdictEmptyInputs {
    verdictCount: number;
    isLoading: boolean;
    verdictStale?: boolean;
    liveStatus?: string;
    mode?: string;
    wsStatus?: string;
    feedStatus?: FeedStatus;
}

const EMPTY_STATE_BY_REASON: Record<VerdictEmptyReason, VerdictEmptyState> = {
    TRANSPORT_DEGRADED: {
        reason: "TRANSPORT_DEGRADED",
        title: "Transport degraded",
        detail: "Live channel is degraded or disconnected. Displaying only last known state until transport recovers.",
        badgeLabel: "TRANSPORT",
        badgeClass: "badge badge-red",
    },
    VERDICT_STALE: {
        reason: "VERDICT_STALE",
        title: "Verdict stale",
        detail: "Latest verdict stream is stale. Awaiting a fresh L12 update before rendering signal cards.",
        badgeLabel: "STALE",
        badgeClass: "badge badge-gold",
    },
    NO_VERDICT_AVAILABLE: {
        reason: "NO_VERDICT_AVAILABLE",
        title: "No verdict available",
        detail: "System is connected but no active L12 verdict payload is currently available.",
        badgeLabel: "NO_DATA",
        badgeClass: "badge badge-muted",
    },
};

export function classifyVerdictEmptyState(inputs: VerdictEmptyInputs): VerdictEmptyState | null {
    if (inputs.isLoading || inputs.verdictCount > 0) return null;

    const transportDegraded =
        inputs.mode === "DEGRADED" ||
        inputs.mode === "RECONNECTING_WS" ||
        inputs.mode === "POLLING_REST" ||
        inputs.mode === "NO_TRANSPORT" ||
        inputs.mode === "NO_PRODUCER" ||
        inputs.wsStatus === "DISCONNECTED" ||
        inputs.wsStatus === "RECONNECTING" ||
        inputs.wsStatus === "DEGRADED" ||
        inputs.feedStatus === "no_transport" ||
        inputs.feedStatus === "config_error" ||
        inputs.feedStatus === "no_producer";

    if (transportDegraded) {
        return EMPTY_STATE_BY_REASON.TRANSPORT_DEGRADED;
    }

    const staleVerdict =
        !!inputs.verdictStale ||
        inputs.liveStatus === "STALE" ||
        inputs.mode === "STALE" ||
        inputs.mode === "STALE_PRESERVED" ||
        inputs.feedStatus === "stale_preserved";

    if (staleVerdict) {
        return EMPTY_STATE_BY_REASON.VERDICT_STALE;
    }

    return EMPTY_STATE_BY_REASON.NO_VERDICT_AVAILABLE;
}
