"use client";

// ============================================================
// useFilteredSignals — Wraps useLiveSignals with EXECUTE + confidence filter.
//
// Only surfaces high-probability signals that passed all 15 layers.
// Respects expires_at to exclude stale/expired signals.
// ============================================================

import { useMemo } from "react";
import type { L12Verdict } from "@/types";

export interface SignalFilterOptions {
    /** Minimum confidence to display (0–1). Default 0.75. */
    minConfidence?: number;
    /** Only show EXECUTE* verdicts. Default true. */
    executeOnly?: boolean;
    /** Exclude signals whose expires_at is in the past. Default true. */
    activeOnly?: boolean;
}

const DEFAULT_MIN_CONFIDENCE = 0.75;

function isExecuteVerdict(verdict: string): boolean {
    return verdict.startsWith("EXECUTE");
}

/**
 * Filter an array of L12Verdict to only high-probability, active signals.
 */
export function filterSignals(
    verdicts: L12Verdict[],
    options: SignalFilterOptions = {}
): L12Verdict[] {
    const {
        minConfidence = DEFAULT_MIN_CONFIDENCE,
        executeOnly = true,
        activeOnly = true,
    } = options;

    const nowSec = Date.now() / 1000;

    return verdicts.filter((v) => {
        if (executeOnly && !isExecuteVerdict(String(v.verdict))) return false;
        if ((v.confidence ?? 0) < minConfidence) return false;
        if (activeOnly && v.expires_at != null && v.expires_at < nowSec) return false;
        return true;
    });
}

/**
 * Hook that derives a filtered subset from live verdicts.
 *
 * Usage:
 *   const { verdicts } = useLiveSignals(initialVerdicts);
 *   const highProbSignals = useFilteredSignals(verdicts, { minConfidence: 0.80 });
 */
export function useFilteredSignals(
    verdicts: L12Verdict[],
    options: SignalFilterOptions = {}
): L12Verdict[] {
    const { minConfidence = DEFAULT_MIN_CONFIDENCE, executeOnly = true, activeOnly = true } = options;

    return useMemo(
        () => filterSignals(verdicts, { minConfidence, executeOnly, activeOnly }),
        [verdicts, minConfidence, executeOnly, activeOnly]
    );
}
