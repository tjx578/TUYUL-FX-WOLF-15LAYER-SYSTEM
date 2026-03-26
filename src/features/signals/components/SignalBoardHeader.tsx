"use client";

import { DomainHeader } from "@/shared/ui/DomainHeader";

interface Props {
    total: number;
    executeCount: number;
}

export function SignalBoardHeader({ total, executeCount }: Props) {
    return (
        <DomainHeader
            domain="signals"
            title="SIGNAL BOARD"
            subtitle="Layer-12 verdicts with live merge and freshness awareness"
            actions={
                <div style={{ display: "flex", gap: 12 }}>
                    <div>
                        <div style={{ fontSize: 11, opacity: 0.7 }}>TOTAL</div>
                        <div style={{ fontWeight: 700 }}>{total}</div>
                    </div>
                    <div>
                        <div style={{ fontSize: 11, opacity: 0.7 }}>EXECUTE</div>
                        <div style={{ fontWeight: 700 }}>{executeCount}</div>
                    </div>
                </div>
            }
        />
    );
}
