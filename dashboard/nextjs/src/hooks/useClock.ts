// ============================================================
// TUYUL FX Wolf-15 — Shared Clock Hook
// Single setInterval shared across all consumers.
// ============================================================
"use client";

import { useEffect, useState } from "react";

const listeners = new Set<() => void>();
let current = Date.now();
let intervalId: ReturnType<typeof setInterval> | null = null;

function tick() {
    current = Date.now();
    listeners.forEach((l) => l());
}

export function useClock(): number {
    const [, rerender] = useState(0);

    useEffect(() => {
        const listener = () => rerender((n) => n + 1);
        listeners.add(listener);
        if (listeners.size === 1) {
            current = Date.now();
            intervalId = setInterval(tick, 1000);
        }
        return () => {
            listeners.delete(listener);
            if (listeners.size === 0 && intervalId) {
                clearInterval(intervalId);
                intervalId = null;
            }
        };
    }, []);

    return current;
}
