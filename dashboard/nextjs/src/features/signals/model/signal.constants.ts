import type { SignalFilterMode } from "./signal.types";

export const SIGNAL_FILTER_MODES: SignalFilterMode[] = [
    "ALL",
    "EXECUTE",
    "HOLD",
    "ABORT",
];

export function isExecuteVerdict(verdict: string): boolean {
    return verdict.startsWith("EXECUTE");
}

export function isHoldVerdict(verdict: string): boolean {
    return verdict === "HOLD";
}

export function isAbortVerdict(verdict: string): boolean {
    return verdict === "ABORT";
}
