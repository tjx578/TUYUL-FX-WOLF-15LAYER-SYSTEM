"use client";

import { bearerHeader } from "@/lib/auth";

export interface TakeSignalAccountOption {
    accountId: string;
    accountName: string;
    broker: string;
    currency: string;
    eaInstanceId?: string | null;
    strategyProfileId?: string | null;

    balance: number;
    equity: number;
    usableCapital?: number;
    readinessScore?: number;

    dailyDdPercent?: number;
    totalDdPercent?: number;
    openRiskPercent?: number;
    openTrades?: number;
    maxConcurrentTrades?: number;

    propFirmCode?: string | null;
    riskState?: "SAFE" | "WARNING" | "CRITICAL";
    eligibilityReason?: string | null;
    selectable?: boolean;
}

export interface RiskPreviewRequest {
    signalRefId: string;
    accountId: string;
    riskPercent: number;
}

export interface RiskPreviewResult {
    accountId: string;
    allowed: boolean;
    lotSize: number;
    riskPercent: number;
    dailyDdAfter: number;
    reason?: string;
}

export interface TakeSignalCommand {
    signalId: string;
    accountId: string;
    eaInstanceId: string;
    operator: string;
    reason: string;
    requestId: string;
    strategyProfileId?: string | null;
    metadata?: Record<string, unknown>;
}

export interface TakeSignalResponseVM {
    takeId: string;
    requestId: string;
    signalId: string;
    accountId: string;
    eaInstanceId: string;
    status:
    | "PENDING"
    | "FIREWALL_APPROVED"
    | "FIREWALL_REJECTED"
    | "EXECUTION_SENT"
    | "EXECUTED"
    | "REJECTED"
    | "CANCELLED"
    | "EXPIRED";
    createdAt: string;
    updatedAt: string;
    statusReason?: string | null;
    firewallResultId?: string | null;
    executionIntentId?: string | null;
}

function getJsonHeaders(extra?: Record<string, string>): Record<string, string> {
    const auth = bearerHeader();

    return {
        "Content-Type": "application/json",
        ...(auth ? { Authorization: auth } : {}),
        "X-Edit-Mode": "ON",
        "X-Action-Reason": "UI_TAKE_SIGNAL",
        ...(process.env.NEXT_PUBLIC_ACTION_PIN
            ? { "X-Action-Pin": process.env.NEXT_PUBLIC_ACTION_PIN }
            : {}),
        ...(extra ?? {}),
    };
}

function unwrapApiResponse<T>(payload: unknown): T {
    if (payload && typeof payload === "object" && "data" in (payload as Record<string, unknown>)) {
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

export async function previewSignalRisk(
    req: RiskPreviewRequest,
): Promise<RiskPreviewResult> {
    const body = {
        verdict_id: req.signalRefId,
        accounts: [{ account_id: req.accountId }],
        risk_percent: req.riskPercent,
        risk_mode: "FIXED",
    };

    const res = await fetch("/api/v1/risk/preview-multi", {
        method: "POST",
        credentials: "include",
        headers: getJsonHeaders({
            "X-Action-Reason": "UI_RISK_PREVIEW",
        }),
        body: JSON.stringify(body),
    });

    if (!res.ok) {
        throw new Error(await parseErrorResponse(res));
    }

    const payload = unwrapApiResponse<{
        previews?: Array<{
            account_id: string;
            lot_size: number;
            risk_percent: number;
            daily_dd_after: number;
            allowed: boolean;
            reason?: string;
        }>
    }>(await res.json());

    const preview = payload?.previews?.[0];
    if (!preview) {
        throw new Error("Risk preview unavailable");
    }

    return {
        accountId: preview.account_id,
        allowed: preview.allowed,
        lotSize: preview.lot_size,
        riskPercent: preview.risk_percent,
        dailyDdAfter: preview.daily_dd_after,
        reason: preview.reason,
    };
}

export async function createTakeSignalBinding(
    command: TakeSignalCommand,
): Promise<TakeSignalResponseVM> {
    const res = await fetch("/api/v1/execution/take-signal", {
        method: "POST",
        credentials: "include",
        headers: getJsonHeaders({
            "X-Idempotency-Key": command.requestId,
        }),
        body: JSON.stringify({
            signal_id: command.signalId,
            account_id: command.accountId,
            ea_instance_id: command.eaInstanceId,
            operator: command.operator,
            reason: command.reason,
            request_id: command.requestId,
            strategy_profile_id: command.strategyProfileId ?? undefined,
            metadata: command.metadata ?? undefined,
        }),
    });

    if (!res.ok) {
        throw new Error(await parseErrorResponse(res));
    }

    const payload = unwrapApiResponse<{
        take_id: string;
        request_id: string;
        signal_id: string;
        account_id: string;
        ea_instance_id: string;
        status: TakeSignalResponseVM["status"];
        created_at: string;
        updated_at: string;
        status_reason?: string | null;
        firewall_result_id?: string | null;
        execution_intent_id?: string | null;
    }>(await res.json());

    return {
        takeId: payload.take_id,
        requestId: payload.request_id,
        signalId: payload.signal_id,
        accountId: payload.account_id,
        eaInstanceId: payload.ea_instance_id,
        status: payload.status,
        createdAt: payload.created_at,
        updatedAt: payload.updated_at,
        statusReason: payload.status_reason ?? null,
        firewallResultId: payload.firewall_result_id ?? null,
        executionIntentId: payload.execution_intent_id ?? null,
    };
}

export function buildTakeSignalRequestId(
    signalId: string,
    accountId: string,
): string {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
        return `take:${signalId}:${accountId}:${crypto.randomUUID()}`;
    }

    return `take:${signalId}:${accountId}:${Date.now()}`;
}
