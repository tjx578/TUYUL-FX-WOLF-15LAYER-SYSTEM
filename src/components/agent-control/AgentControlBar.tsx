/**
 * @deprecated Use `AgentManagerActions` from `@/components/agent-manager` instead. Sunset: 2026-06-01
 */
"use client";

import { useEffect, useRef } from "react";
import { useState } from "react";
import Button from "@/components/ui/Button";

interface Props {
    safeMode: boolean;
    cooldownActive: boolean;
    onRestart: () => Promise<{ success: boolean; error?: string }>;
    onSetSafeMode: (enabled: boolean, reason: string) => Promise<{ success: boolean; error?: string }>;
}

/** @deprecated Use AgentManagerActions from @/components/agent-manager instead. Sunset: 2026-06-01 */
export function AgentControlBar({ safeMode, cooldownActive, onRestart, onSetSafeMode }: Props) {
    const warnedRef = useRef(false);
    useEffect(() => {
        if (!warnedRef.current) {
            warnedRef.current = true;
            console.warn("[DEPRECATED] AgentControlBar: Use AgentManagerActions from @/components/agent-manager instead");
        }
    }, []);

    const [restartLoading, setRestartLoading] = useState(false);
    const [safeModeLoading, setSafeModeLoading] = useState(false);
    const [feedback, setFeedback] = useState<{ type: "ok" | "error"; text: string } | null>(null);

    const handleRestart = async () => {
        setRestartLoading(true);
        setFeedback(null);
        const result = await onRestart();
        setRestartLoading(false);
        setFeedback(
            result.success
                ? { type: "ok", text: "Restart queued successfully" }
                : { type: "error", text: result.error ?? "Restart failed" }
        );
    };

    const handleSafeModeToggle = async () => {
        setSafeModeLoading(true);
        setFeedback(null);
        const reason = safeMode ? "Disable safe mode from dashboard" : "Enable safe mode from dashboard";
        const result = await onSetSafeMode(!safeMode, reason);
        setSafeModeLoading(false);
        setFeedback(
            result.success
                ? { type: "ok", text: `Safe mode ${safeMode ? "disabled" : "enabled"}` }
                : { type: "error", text: result.error ?? "Toggle failed" }
        );
    };

    return (
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <Button
                variant="danger"
                onClick={handleRestart}
                disabled={restartLoading || cooldownActive}
            >
                {restartLoading ? "Restarting..." : cooldownActive ? "COOLDOWN" : "RESTART EA"}
            </Button>

            <Button
                variant={safeMode ? "primary" : "ghost"}
                onClick={handleSafeModeToggle}
                disabled={safeModeLoading}
            >
                {safeModeLoading
                    ? "Updating..."
                    : safeMode
                        ? "DISABLE SAFE MODE"
                        : "ENABLE SAFE MODE"}
            </Button>

            {feedback && (
                <span
                    style={{
                        fontSize: 11,
                        fontWeight: 600,
                        color: feedback.type === "ok" ? "var(--green)" : "var(--red)",
                    }}
                >
                    {feedback.text}
                </span>
            )}
        </div>
    );
}
