"use client";

// ============================================================
// useSignalNotifications — Browser Web Notifications for EXECUTE signals.
//
// Fires a desktop notification when a NEW high-probability signal appears
// that wasn't in the previous render. Respects expires_at (no notification
// for already-expired signals). Deduplicates via a seen-set.
// ============================================================

import { useEffect, useRef, useCallback } from "react";
import type { L12Verdict } from "@/types";

/**
 * Request browser notification permission on mount.
 * Returns a stable callback that shows a notification.
 */
function useNotificationPermission() {
    useEffect(() => {
        if (typeof window === "undefined") return;
        if (!("Notification" in window)) return;
        if (Notification.permission === "default") {
            Notification.requestPermission();
        }
    }, []);

    const notify = useCallback((title: string, body: string) => {
        if (typeof window === "undefined") return;
        if (!("Notification" in window)) return;
        if (Notification.permission !== "granted") return;
        new Notification(title, {
            body,
            icon: "/wolf-icon.png",
            tag: `wolf15-signal-${Date.now()}`,
        });
    }, []);

    return notify;
}

/**
 * useSignalNotifications
 *
 * Pass the filtered (EXECUTE + high-confidence) signals array.
 * When a new signal_id/symbol appears that wasn't seen before,
 * a browser notification fires.
 */
export function useSignalNotifications(
    signals: L12Verdict[],
    enabled = true
): void {
    const notify = useNotificationPermission();
    const seenRef = useRef<Set<string>>(new Set());
    const initializedRef = useRef(false);

    useEffect(() => {
        if (!enabled) return;

        // On first render, populate seenRef without firing notifications
        if (!initializedRef.current) {
            for (const sig of signals) {
                seenRef.current.add(sig.symbol);
            }
            initializedRef.current = true;
            return;
        }

        const nowSec = Date.now() / 1000;

        for (const sig of signals) {
            const key = sig.symbol;
            if (seenRef.current.has(key)) continue;

            // Skip if signal is expired
            if (sig.expires_at != null && sig.expires_at < nowSec) continue;

            seenRef.current.add(key);

            const dir = sig.direction ?? "";
            const conf = Math.round((sig.confidence ?? 0) * 100);
            const rr = sig.risk_reward_ratio ? `R:R 1:${sig.risk_reward_ratio.toFixed(1)}` : "";

            notify(
                `WOLF-15 EXECUTE: ${sig.symbol} ${dir}`,
                `Confidence ${conf}% ${rr} — ${String(sig.verdict)}`.trim()
            );
        }

        // Prune symbols that dropped out of the filtered list
        const currentSymbols = new Set(signals.map((s) => s.symbol));
        for (const key of seenRef.current) {
            if (!currentSymbols.has(key)) {
                seenRef.current.delete(key);
            }
        }
    }, [signals, enabled, notify]);
}
