"use client";

interface Props {
    total: number;
    executeCount: number;
}

export function SignalBoardHeader({ total, executeCount }: Props) {
    return (
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
            <div>
                <h1 style={{ margin: 0, fontSize: 22 }}>SIGNAL BOARD</h1>
                <p style={{ margin: "4px 0 0", opacity: 0.7 }}>
                    Layer-12 verdicts with live merge and freshness awareness
                </p>
            </div>

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
        </div>
    );
}
