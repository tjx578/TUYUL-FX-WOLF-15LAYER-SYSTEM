"use client";

import { useCallback, useEffect, useState } from "react";
import type { Trade } from "@/types";
import { apiFetch } from "@/lib/fetcher";

export interface ActiveTradesResponse {
    trades: Trade[];
    count: number;
}

const TRADE_ENDPOINTS = {
    active: "/api/v1/trades/active",
    confirmById: (tradeId: string) => `/api/v1/trades/${encodeURIComponent(tradeId)}/confirm`,
    close: "/api/v1/trades/close",
} as const;

async function parseJsonOrText(res: Response): Promise<string> {
    try {
        const json = await res.json();
        if (typeof json?.detail === "string") return json.detail;
        if (typeof json?.error === "string") return json.error;
        if (typeof json?.message === "string") return json.message;
        return JSON.stringify(json);
    } catch {
        try {
            return await res.text();
        } catch {
            return `${res.status} ${res.statusText}`;
        }
    }
}

async function fetchActiveTrades(): Promise<ActiveTradesResponse | Trade[]> {
    const res = await apiFetch(TRADE_ENDPOINTS.active);
    if (!res.ok) {
        throw new Error(await parseJsonOrText(res));
    }
    return (await res.json()) as ActiveTradesResponse | Trade[];
}

export function useActiveTrades() {
    const [data, setData] = useState<ActiveTradesResponse | Trade[] | undefined>(undefined);
    const [error, setError] = useState<unknown>(undefined);
    const [isLoading, setIsLoading] = useState(true);

    const mutate = useCallback(async () => {
        setIsLoading(true);
        try {
            const next = await fetchActiveTrades();
            setData(next);
            setError(undefined);
        } catch (err) {
            setError(err);
        } finally {
            setIsLoading(false);
        }
    }, []);

    useEffect(() => {
        void mutate();
        const id = setInterval(() => {
            void mutate();
        }, 5_000);
        return () => clearInterval(id);
    }, [mutate]);

    return { data, isLoading, isError: !!error, error, mutate };
}

export async function confirmTrade(tradeId: string): Promise<void> {
    const res = await apiFetch(TRADE_ENDPOINTS.confirmById(tradeId), {
        method: "POST",
        headers: {
            "X-Idempotency-Key": `confirm:${tradeId}`,
        },
    });

    if (!res.ok) {
        throw new Error(await parseJsonOrText(res));
    }
}

export async function closeTrade(tradeId: string, reason: string): Promise<void> {
    const res = await apiFetch(TRADE_ENDPOINTS.close, {
        method: "POST",
        body: JSON.stringify({ trade_id: tradeId, reason }),
    });

    if (!res.ok) {
        throw new Error(await parseJsonOrText(res));
    }
}
