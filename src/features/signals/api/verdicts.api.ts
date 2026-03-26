"use client";

import { apiFetch } from "@/lib/fetcher";

export interface TakeSignalRequest {
    verdict_id: string;
    accounts: string[];
    pair: string;
    direction: "BUY" | "SELL";
    entry: number;
    sl: number;
    tp: number;
    risk_percent: number;
    operator?: string;
}

export interface RiskPreviewMultiRequest {
    verdict_id: string;
    accounts: Array<{ account_id: string }>;
    risk_percent: number;
    risk_mode: "FIXED" | "SPLIT";
}

export interface RiskPreviewAccountItem {
    account_id: string;
    lot_size: number;
    risk_percent: number;
    daily_dd_after: number;
    allowed: boolean;
    reason?: string;
}

export interface SkipSignalRequest {
    signal_id: string;
    pair?: string;
    reason?: string;
}

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

export async function takeSignal(req: TakeSignalRequest): Promise<void> {
    const res = await apiFetch("/api/v1/signals/take", {
        method: "POST",
        body: JSON.stringify(req),
    });

    if (!res.ok) {
        throw new Error(await parseJsonOrText(res));
    }
}

export async function previewRiskMulti(
    req: RiskPreviewMultiRequest
): Promise<{ previews: RiskPreviewAccountItem[] }> {
    const res = await apiFetch("/api/v1/risk/preview/multi", {
        method: "POST",
        body: JSON.stringify(req),
    });

    if (!res.ok) {
        throw new Error(await parseJsonOrText(res));
    }

    return (await res.json()) as { previews: RiskPreviewAccountItem[] };
}

export async function skipSignal(req: SkipSignalRequest): Promise<void> {
    const res = await apiFetch("/api/v1/signals/skip", {
        method: "POST",
        body: JSON.stringify(req),
    });

    if (!res.ok) {
        throw new Error(await parseJsonOrText(res));
    }
}
