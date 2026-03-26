"use client";

// ============================================================
// TUYUL FX Wolf-15 — Create Account Modal
// Full-featured modal for account creation with prop firm options.
// ============================================================

import { useState, useEffect } from "react";
import type { AccountCreate } from "@/types";
import { createAccount } from "../api/accounts.api";
import { fetchPropFirms, fetchPropFirmPrograms, fetchPropFirmRules } from "@/shared/api/propfirm.api";
import Panel from "@/components/ui/Panel";

interface PropFirmItem {
    code: string;
    name: string;
}

interface ProgramItem {
    code: string;
    name: string;
}

interface PropFirmRules {
    max_daily_loss?: number;
    max_total_loss?: number;
    [key: string]: unknown;
}

interface CreateAccountModalProps {
    onCreated: () => void;
    onCancel: () => void;
}

export default function CreateAccountModal({ onCreated, onCancel }: CreateAccountModalProps) {
    const [form, setForm] = useState<
        AccountCreate & {
            prop_firm: boolean;
            data_source: "MANUAL" | "EA";
        }
    >({
        broker: "",
        account_name: "",
        program_code: "",
        phase_code: "funded",
        balance: 0,
        equity: 0,
        prop_firm_code: "",
        currency: "USD",
        prop_firm: false,
        data_source: "MANUAL",
    });
    const [firms, setFirms] = useState<PropFirmItem[]>([]);
    const [programs, setPrograms] = useState<ProgramItem[]>([]);
    const [rules, setRules] = useState<PropFirmRules | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [submitting, setSubmitting] = useState(false);

    useEffect(() => {
        if (!form.prop_firm) {
            setFirms([]);
            return;
        }

        void fetchPropFirms().then((res) => setFirms(res.items ?? []));
    }, [form.prop_firm]);

    useEffect(() => {
        if (!form.prop_firm || !form.prop_firm_code) {
            setPrograms([]);
            return;
        }

        void fetchPropFirmPrograms(form.prop_firm_code).then((res) => setPrograms(res.items ?? []));
    }, [form.prop_firm, form.prop_firm_code]);

    useEffect(() => {
        if (!form.prop_firm || !form.prop_firm_code || !form.program_code) {
            setRules(null);
            return;
        }

        void fetchPropFirmRules(form.prop_firm_code, form.program_code, form.phase_code || "funded").then((res) => setRules(res));
    }, [form.prop_firm, form.prop_firm_code, form.program_code, form.phase_code]);

    const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
        e.preventDefault();
        if (!form.broker || !form.account_name || form.balance <= 0) {
            setError("Please fill all required fields");
            return;
        }
        setSubmitting(true);
        setError(null);
        try {
            await createAccount({
                ...form,
                equity: form.equity || form.balance,
                prop_firm_code: form.prop_firm ? form.prop_firm_code : undefined,
            });
            onCreated();
        } catch (err: unknown) {
            setError(err instanceof Error ? err.message : "Failed to create account");
        } finally {
            setSubmitting(false);
        }
    };

    const inputStyle: React.CSSProperties = {
        width: "100%",
        padding: "8px 10px",
        fontSize: 12,
        background: "var(--bg-base)",
        border: "1px solid var(--bg-border)",
        borderRadius: 4,
        color: "var(--text-primary)",
        outline: "none",
    };

    const labelStyle: React.CSSProperties = {
        fontSize: 10,
        fontWeight: 600,
        color: "var(--text-muted)",
        letterSpacing: "0.06em",
        marginBottom: 4,
        display: "block",
    };

    return (
        <div
            role="dialog"
            aria-modal="true"
            aria-label="Create account"
            style={{
                position: "fixed",
                inset: 0,
                background: "var(--bg-overlay, rgba(0,0,0,0.6))",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                zIndex: 100,
                padding: 16,
                backdropFilter: "blur(4px)",
            }}
            onClick={onCancel}
        >
            <div className="animate-fade-in" onClick={(e) => e.stopPropagation()}>
                <Panel className="w-[440px] max-w-[90vw] flex flex-col gap-4">
                    <div
                        style={{
                            fontSize: 14,
                            fontWeight: 800,
                            color: "var(--text-primary)",
                            letterSpacing: "0.04em",
                        }}
                    >
                        CREATE ACCOUNT
                    </div>
                    <p style={{ fontSize: 10, color: "var(--text-muted)", margin: 0 }}>
                        Add a new capital account for deployment tracking.
                    </p>

                    <form
                        onSubmit={handleSubmit}
                        style={{ display: "flex", flexDirection: "column", gap: 12 }}
                    >
                        {/* Account name */}
                        <div>
                            <label style={labelStyle}>ACCOUNT NAME *</label>
                            <input
                                name="account_name"
                                style={inputStyle}
                                value={form.account_name}
                                onChange={(e) => setForm({ ...form, account_name: e.target.value })}
                                placeholder="My Trading Account"
                                maxLength={120}
                            />
                        </div>

                        {/* Broker */}
                        <div>
                            <label style={labelStyle}>BROKER *</label>
                            <input
                                name="broker"
                                style={inputStyle}
                                value={form.broker}
                                onChange={(e) => setForm({ ...form, broker: e.target.value })}
                                placeholder="IC Markets"
                                maxLength={80}
                            />
                        </div>

                        {/* Balance + Currency */}
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                            <div>
                                <label style={labelStyle}>BALANCE *</label>
                                <input
                                    name="balance"
                                    style={inputStyle}
                                    type="number"
                                    value={form.balance || ""}
                                    onChange={(e) => setForm({ ...form, balance: parseFloat(e.target.value) || 0 })}
                                    placeholder="10000"
                                    min="0"
                                    step="0.01"
                                />
                            </div>
                            <div>
                                <label style={labelStyle}>CURRENCY</label>
                                <select
                                    name="currency"
                                    style={inputStyle}
                                    value={form.currency}
                                    onChange={(e) => setForm({ ...form, currency: e.target.value })}
                                >
                                    <option value="USD">USD</option>
                                    <option value="EUR">EUR</option>
                                    <option value="GBP">GBP</option>
                                </select>
                            </div>
                        </div>

                        {/* Data source toggle */}
                        <div>
                            <label style={labelStyle}>DATA SOURCE</label>
                            <div style={{ display: "flex", gap: 8 }}>
                                {(["MANUAL", "EA"] as const).map((src) => (
                                    <button
                                        key={src}
                                        type="button"
                                        className={`btn ${form.data_source === src ? "btn-primary" : "btn-ghost"}`}
                                        style={{ fontSize: 10, padding: "4px 12px" }}
                                        onClick={() => setForm({ ...form, data_source: src })}
                                    >
                                        {src}
                                    </button>
                                ))}
                            </div>
                        </div>

                        {/* Prop firm toggle */}
                        <div>
                            <label style={{ ...labelStyle, display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                                <input
                                    name="prop_firm"
                                    type="checkbox"
                                    checked={form.prop_firm}
                                    onChange={(e) => setForm({ ...form, prop_firm: e.target.checked })}
                                    style={{ accentColor: "var(--accent, var(--yellow))" }}
                                />
                                PROP FIRM ACCOUNT
                            </label>
                        </div>

                        {/* Prop firm code */}
                        {form.prop_firm && (
                            <div>
                                <label style={labelStyle}>PROP FIRM CODE</label>
                                {firms.length > 0 ? (
                                    <select
                                        name="prop_firm_code"
                                        style={inputStyle}
                                        value={form.prop_firm_code ?? ""}
                                        onChange={(e) => setForm({ ...form, prop_firm_code: e.target.value || "" })}
                                    >
                                        <option value="">Select prop firm</option>
                                        {firms.map((firm) => (
                                            <option key={firm.code} value={firm.code}>
                                                {firm.name} ({firm.code})
                                            </option>
                                        ))}
                                    </select>
                                ) : (
                                    <input
                                        name="prop_firm_code"
                                        style={inputStyle}
                                        value={form.prop_firm_code ?? ""}
                                        onChange={(e) => setForm({ ...form, prop_firm_code: e.target.value || "" })}
                                        placeholder="FTMO / MFF / TFT"
                                        maxLength={64}
                                    />
                                )}
                            </div>
                        )}

                        {form.prop_firm && form.prop_firm_code && programs.length > 0 && (
                            <div>
                                <label style={labelStyle}>PROGRAM</label>
                                <select
                                    name="program_code"
                                    style={inputStyle}
                                    value={form.program_code ?? ""}
                                    onChange={(e) => setForm({ ...form, program_code: e.target.value || "" })}
                                >
                                    <option value="">Select program</option>
                                    {programs.map((program) => (
                                        <option key={program.code} value={program.code}>
                                            {program.name} ({program.code})
                                        </option>
                                    ))}
                                </select>
                            </div>
                        )}

                        {form.prop_firm && (
                            <div>
                                <label style={labelStyle}>PHASE</label>
                                <select
                                    name="phase_code"
                                    style={inputStyle}
                                    value={form.phase_code ?? "funded"}
                                    onChange={(e) => setForm({ ...form, phase_code: e.target.value || "funded" })}
                                >
                                    <option value="challenge">challenge</option>
                                    <option value="verification">verification</option>
                                    <option value="funded">funded</option>
                                </select>
                            </div>
                        )}

                        {rules && (
                            <div style={{ fontSize: 10, color: "var(--text-muted)", display: "grid", gap: 4 }}>
                                <div>Max Daily Loss: {rules.max_daily_loss ?? "-"}</div>
                                <div>Max Total Loss: {rules.max_total_loss ?? "-"}</div>
                            </div>
                        )}

                        {error && (
                            <div style={{ fontSize: 11, color: "var(--red)", padding: "4px 0" }}>
                                {error}
                            </div>
                        )}

                        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 4 }}>
                            <button
                                type="button"
                                className="btn btn-ghost"
                                style={{ fontSize: 11 }}
                                onClick={onCancel}
                            >
                                CANCEL
                            </button>
                            <button
                                type="submit"
                                className="btn btn-primary"
                                style={{ fontSize: 11 }}
                                disabled={submitting}
                            >
                                {submitting ? "CREATING..." : "CREATE ACCOUNT"}
                            </button>
                        </div>
                    </form>
                </Panel>
            </div>
        </div>
    );
}
