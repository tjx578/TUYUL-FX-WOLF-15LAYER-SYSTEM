"use client";

import { useCallback, useMemo, useState } from "react";
import type { SignalViewModel } from "../model/signal.types";
import {
    buildTakeSignalRequestId,
    createTakeSignalBinding,
    previewSignalRisk,
    type RiskPreviewResult,
    type TakeSignalAccountOption,
    type TakeSignalResponseVM,
} from "../api/signalActions.api";

export interface UseTakeSignalFlowParams {
    signal: SignalViewModel | null;
    accounts: TakeSignalAccountOption[];
    operatorId: string;
    defaultReason?: string;
    defaultRiskPercent?: number;
    onSubmitted?: (result: TakeSignalResponseVM) => void;
}

export interface TakeSignalFlowState {
    isOpen: boolean;
    selectedAccountId: string | null;
    riskPercent: number;
    reason: string;
    isPreviewing: boolean;
    isSubmitting: boolean;
    preview: RiskPreviewResult | null;
    error: string | null;
    selectedAccount: TakeSignalAccountOption | null;
    canSubmit: boolean;
    open: () => void;
    close: () => void;
    selectAccount: (accountId: string) => void;
    setRiskPercent: (value: number) => void;
    setReason: (value: string) => void;
    runPreview: () => Promise<void>;
    submit: () => Promise<TakeSignalResponseVM | null>;
    resetError: () => void;
}

export function useTakeSignalFlow({
    signal,
    accounts,
    operatorId,
    defaultReason = process.env.NEXT_PUBLIC_DEFAULT_TAKE_REASON || "MANUAL_OPERATOR_TAKE",
    defaultRiskPercent = 0.5,
    onSubmitted,
}: UseTakeSignalFlowParams): TakeSignalFlowState {
    const [isOpen, setIsOpen] = useState(false);
    const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null);
    const [riskPercent, setRiskPercentState] = useState<number>(defaultRiskPercent);
    const [reason, setReasonState] = useState<string>(defaultReason);
    const [isPreviewing, setIsPreviewing] = useState(false);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [preview, setPreview] = useState<RiskPreviewResult | null>(null);
    const [error, setError] = useState<string | null>(null);

    const selectedAccount = useMemo(
        () => accounts.find((a) => a.accountId === selectedAccountId) ?? null,
        [accounts, selectedAccountId],
    );

    const close = useCallback(() => {
        setIsOpen(false);
        setPreview(null);
        setError(null);
    }, []);

    const open = useCallback(() => {
        setIsOpen(true);
    }, []);

    const selectAccount = useCallback((accountId: string) => {
        setSelectedAccountId(accountId);
        setPreview(null);
        setError(null);
    }, []);

    const setRiskPercent = useCallback((value: number) => {
        setRiskPercentState(value);
        setPreview(null);
    }, []);

    const setReason = useCallback((value: string) => {
        setReasonState(value);
    }, []);

    const resetError = useCallback(() => setError(null), []);

    const runPreview = useCallback(async () => {
        if (!signal) {
            setError("No signal selected");
            return;
        }

        if (!selectedAccount) {
            setError("Select an account first");
            return;
        }

        if (!selectedAccount.selectable) {
            setError(selectedAccount.eligibilityReason || "Selected account is not eligible");
            return;
        }

        const signalRefId = signal.backendRefId ?? signal.signalId;
        if (!signalRefId) {
            setError("Signal backend reference is missing. Cannot preview risk safely.");
            return;
        }

        setIsPreviewing(true);
        setError(null);

        try {
            const result = await previewSignalRisk({
                signalRefId,
                accountId: selectedAccount.accountId,
                riskPercent,
            });
            setPreview(result);
        } catch (err) {
            setPreview(null);
            setError(err instanceof Error ? err.message : "Risk preview failed");
        } finally {
            setIsPreviewing(false);
        }
    }, [signal, selectedAccount, riskPercent]);

    const canSubmit = useMemo(() => {
        if (!signal?.signalId) return false;
        if (!selectedAccount?.eaInstanceId) return false;
        if (!selectedAccount?.selectable) return false;
        if (!preview?.allowed) return false;
        if (isPreviewing || isSubmitting) return false;
        if (!reason.trim()) return false;
        return true;
    }, [signal?.signalId, selectedAccount, preview, isPreviewing, isSubmitting, reason]);

    const submit = useCallback(async () => {
        if (!signal?.signalId) {
            setError("Authoritative signal_id is missing");
            return null;
        }

        if (!selectedAccount) {
            setError("No account selected");
            return null;
        }

        if (!selectedAccount.eaInstanceId) {
            setError("Selected account has no EA instance binding");
            return null;
        }

        if (!selectedAccount.selectable) {
            setError(selectedAccount.eligibilityReason || "Selected account is not eligible");
            return null;
        }

        if (!preview?.allowed) {
            setError(preview?.reason || "Risk preview has not approved this take action");
            return null;
        }

        setIsSubmitting(true);
        setError(null);

        try {
            const result = await createTakeSignalBinding({
                signalId: signal.signalId,
                accountId: selectedAccount.accountId,
                eaInstanceId: selectedAccount.eaInstanceId,
                operator: operatorId,
                reason: reason.trim(),
                requestId: buildTakeSignalRequestId(signal.signalId, selectedAccount.accountId),
                strategyProfileId: selectedAccount.strategyProfileId ?? undefined,
                metadata: {
                    symbol: signal.symbol,
                    verdict: signal.verdict,
                    confidence: signal.confidence,
                    risk_percent: riskPercent,
                    preview_lot_size: preview.lotSize,
                    source: "dashboard:signals",
                },
            });

            onSubmitted?.(result);
            close();
            return result;
        } catch (err) {
            setError(err instanceof Error ? err.message : "Take signal failed");
            return null;
        } finally {
            setIsSubmitting(false);
        }
    }, [
        signal,
        selectedAccount,
        preview,
        operatorId,
        reason,
        riskPercent,
        onSubmitted,
        close,
    ]);

    return {
        isOpen,
        selectedAccountId,
        riskPercent,
        reason,
        isPreviewing,
        isSubmitting,
        preview,
        error,
        selectedAccount,
        canSubmit,
        open,
        close,
        selectAccount,
        setRiskPercent,
        setReason,
        runPreview,
        submit,
        resetError,
    };
}
