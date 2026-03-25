"use client";

import { bearerHeader } from "@/lib/auth";
import type { TradeLifecycleBridgeViewModel } from "../model/trade.types";

function unwrapApiResponse<T>(payload: unknown): T {
    if (
        payload &&
        typeof payload === "object" &&
        "data" in (payload as Record<string, unknown>)
    ) {
        return (payload as { data: T }).data;
    }
    return payload as T;
}

async function parseErrorResponse(res: Response): Promise<string> {
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

export async function fetchTakeSignalLifecycle(
    takeId: string,
): Promise<TradeLifecycleBridgeViewModel> {
    const auth = bearerHeader();

    const res = await fetch(`/api/v1/execution/take-signal/${encodeURIComponent(takeId)}`, {
        method: "GET",
        credentials: "include",
        headers: {
            ...(auth ? { Authorization: auth } : {}),
        },
    });

    if (!res.ok) {
        throw new Error(await parseErrorResponse(res));
    }

    const payload = unwrapApiResponse<{
        take_id: string;
        signal_id: string;
        account_id: string;
        status: TradeLifecycleBridgeViewModel["status"];
        status_reason?: string | null;
        execution_intent_id?: string | null;
        firewall_result_id?: string | null;
    }>(await res.json());

    return {
        takeId: payload.take_id,
        signalId: payload.signal_id,
        accountId: payload.account_id,
        status: payload.status ?? "UNKNOWN",
        statusReason: payload.status_reason ?? null,
        executionIntentId: payload.execution_intent_id ?? null,
        firewallResultId: payload.firewall_result_id ?? null,
    };
}
