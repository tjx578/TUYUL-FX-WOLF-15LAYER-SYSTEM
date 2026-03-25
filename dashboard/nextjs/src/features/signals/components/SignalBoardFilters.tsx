"use client";

import { SIGNAL_FILTER_MODES } from "../model/signal.constants";
import type { SignalFilterMode } from "../model/signal.types";

interface Props {
    query: string;
    onQueryChange: (value: string) => void;
    mode: SignalFilterMode;
    onModeChange: (value: SignalFilterMode) => void;
}

export function SignalBoardFilters({
    query,
    onQueryChange,
    mode,
    onModeChange,
}: Props) {
    return (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input
                value={query}
                onChange={(e) => onQueryChange(e.target.value)}
                placeholder="Search pair..."
                style={{
                    padding: "8px 10px",
                    minWidth: 220,
                    borderRadius: 8,
                    border: "1px solid rgba(255,255,255,0.12)",
                    background: "transparent",
                    color: "inherit",
                }}
            />

            {SIGNAL_FILTER_MODES.map((m) => (
                <button
                    key={m}
                    onClick={() => onModeChange(m)}
                    style={{
                        padding: "8px 10px",
                        borderRadius: 8,
                        border: "1px solid rgba(255,255,255,0.12)",
                        background: mode === m ? "rgba(255,255,255,0.12)" : "transparent",
                        color: "inherit",
                        cursor: "pointer",
                    }}
                >
                    {m}
                </button>
            ))}
        </div>
    );
}
