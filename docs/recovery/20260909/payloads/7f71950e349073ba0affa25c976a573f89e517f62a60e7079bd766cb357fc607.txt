"use client";

// ============================================================
// TUYUL FX Wolf-15 — SignalRationaleDrawer
// Deep rationale inspection panel for a single L12Verdict.
// Read-only — TAKE redirects to Signal Board.
// ============================================================

import { useRouter } from "next/navigation";
import { usePipeline } from "@/lib/api";
import { GateStatus } from "@/components/GateStatus";
import { formatTime } from "@/lib/timezone";
import type { L12Verdict } from "@/types";

interface SignalRationaleDrawerProps {
  verdict: L12Verdict;
  onClose: () => void;
}

function ScoreGauge({ label, value, max = 100 }: { label: string; value: number; max?: number }) {
  const pct = Math.min((value / max) * 100, 100);
  const color =
    pct >= 70 ? "var(--green)" :
    pct >= 50 ? "var(--yellow)" :
    "var(--red)";

  return (
    <div style={{ flex: 1, minWidth: 80 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginBottom: 6,
          fontSize: 9,
          letterSpacing: "0.08em",
          color: "var(--text-muted)",
        }}
      >
        <span>{label}</span>
        <span style={{ color, fontFamily: "var(--font-mono)", fontWeight: 700 }}>
          {value.toFixed(0)}
        </span>
      </div>
      <div
        style={{
          height: 5,
          borderRadius: 3,
          background: "var(--bg-elevated)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            background: color,
            borderRadius: 3,
            transition: "width 0.4s ease",
          }}
        />
      </div>
    </div>
  );
}

function PriceGrid({ verdict }: { verdict: L12Verdict }) {
  const isExecutable = String(verdict.verdict).startsWith("EXECUTE");
  if (!isExecutable) return null;

  const items = [
    { label: "ENTRY", value: verdict.entry_price },
    { label: "STOP LOSS", value: verdict.stop_loss },
    { label: "TP1", value: verdict.take_profit_1 },
    { label: "TP2", value: verdict.take_profit_2 },
  ].filter((i) => i.value != null);

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(${Math.min(items.length, 4)}, 1fr)`,
        gap: 8,
        marginTop: 4,
      }}
    >
      {items.map(({ label, value }) => (
        <div
          key={label}
          style={{
            background: "var(--bg-elevated)",
            border: "1px solid var(--border-default)",
            borderRadius: "var(--radius-sm)",
            padding: "8px 10px",
          }}
        >
          <div style={{ fontSize: 8, letterSpacing: "0.1em", color: "var(--text-muted)", marginBottom: 3 }}>
            {label}
          </div>
          <div style={{ fontSize: 13, fontFamily: "var(--font-mono)", color: "var(--text-primary)", fontWeight: 600 }}>
            {value!.toFixed(5)}
          </div>
        </div>
      ))}
    </div>
  );
}

function PipelineSection({ pair }: { pair: string }) {
  const { data, isLoading } = usePipeline(pair);

  if (isLoading) {
    return (
      <div style={{ fontSize: 10, color: "var(--text-muted)", padding: "10px 0" }}>
        Loading pipeline…
      </div>
    );
  }

  if (!data) return null;

  return (
    <div>
      <div
        style={{
          fontSize: 9,
          letterSpacing: "0.1em",
          color: "var(--text-muted)",
          marginBottom: 8,
          fontWeight: 700,
        }}
      >
        PIPELINE STATE
      </div>
      <div
        style={{
          padding: "10px 12px",
          background: "var(--bg-elevated)",
          border: "1px solid var(--border-default)",
          borderRadius: "var(--radius-md)",
          fontSize: 11,
          fontFamily: "var(--font-mono)",
          color: "var(--text-secondary)",
          lineHeight: 1.6,
        }}
      >
        <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
          {JSON.stringify(data, null, 2)}
        </pre>
      </div>
    </div>
  );
}

export function SignalRationaleDrawer({ verdict, onClose }: SignalRationaleDrawerProps) {
  const router = useRouter();
  const isExecutable = String(verdict.verdict).startsWith("EXECUTE");
  const confidencePct = Math.round((verdict.confidence ?? 0) * 100);
  const dirColor = verdict.direction === "BUY" ? "var(--green)" : verdict.direction === "SELL" ? "var(--red)" : "var(--text-muted)";
  const passedGates = verdict.gates?.filter((g) => g.passed).length ?? 0;
  const totalGates = verdict.gates?.length ?? 0;

  return (
    <div
      style={{
        width: 420,
        flexShrink: 0,
        background: "var(--bg-panel)",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--radius-lg)",
        display: "flex",
        flexDirection: "column",
        maxHeight: "calc(100vh - 160px)",
        overflow: "hidden",
      }}
    >
      {/* Sticky header */}
      <div
        style={{
          padding: "14px 16px",
          borderBottom: "1px solid var(--border-default)",
          display: "flex",
          alignItems: "center",
          gap: 10,
          flexShrink: 0,
        }}
      >
        <span
          style={{
            fontSize: 16,
            fontWeight: 800,
            letterSpacing: "0.05em",
            fontFamily: "var(--font-display)",
            color: "var(--text-primary)",
          }}
        >
          {verdict.symbol}
        </span>
        {verdict.direction && (
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              color: dirColor,
              background: verdict.direction === "BUY" ? "rgba(0,230,118,0.10)" : "rgba(255,61,87,0.10)",
              border: `1px solid ${dirColor}40`,
              borderRadius: "var(--radius-sm)",
              padding: "2px 7px",
              letterSpacing: "0.08em",
            }}
          >
            {verdict.direction}
          </span>
        )}
        <span
          style={{
            fontSize: 9,
            letterSpacing: "0.08em",
            color: "var(--text-muted)",
            fontFamily: "var(--font-mono)",
          }}
        >
          {formatTime(verdict.timestamp * 1000)}
        </span>
        <button
          onClick={onClose}
          style={{
            marginLeft: "auto",
            background: "transparent",
            border: "1px solid var(--border-strong)",
            color: "var(--text-muted)",
            borderRadius: 4,
            padding: "3px 8px",
            fontSize: 11,
            cursor: "pointer",
          }}
        >
          ✕
        </button>
      </div>

      {/* Scrollable body */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "14px 16px",
          display: "flex",
          flexDirection: "column",
          gap: 18,
        }}
      >
        {/* Verdict + Confidence */}
        <div>
          <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "var(--text-muted)", marginBottom: 8 }}>VERDICT</div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
            <span
              style={{
                fontSize: 14,
                fontWeight: 800,
                letterSpacing: "0.06em",
                color: isExecutable ? "var(--green)" : "var(--text-muted)",
                fontFamily: "var(--font-display)",
              }}
            >
              {verdict.verdict}
            </span>
            <span
              style={{
                fontSize: 10,
                fontFamily: "var(--font-mono)",
                color: confidencePct >= 80 ? "var(--green)" : confidencePct >= 60 ? "var(--yellow)" : "var(--red)",
                fontWeight: 700,
              }}
            >
              {confidencePct}% confidence
            </span>
          </div>
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{
                width: `${confidencePct}%`,
                background:
                  confidencePct >= 75 ? "var(--green)" :
                  confidencePct >= 50 ? "var(--yellow)" :
                  "var(--red)",
              }}
            />
          </div>
        </div>

        {/* Price levels */}
        {isExecutable && (
          <div>
            <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "var(--text-muted)", marginBottom: 6 }}>
              PRICE LEVELS
            </div>
            <PriceGrid verdict={verdict} />
            {verdict.risk_reward_ratio && (
              <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 10, color: "var(--text-muted)" }}>R:R Ratio</span>
                <span
                  style={{
                    fontSize: 12,
                    fontFamily: "var(--font-mono)",
                    fontWeight: 700,
                    color: verdict.risk_reward_ratio >= 2 ? "var(--green)" : "var(--yellow)",
                  }}
                >
                  1:{verdict.risk_reward_ratio.toFixed(2)}
                </span>
              </div>
            )}
          </div>
        )}

        {/* L12 Scores */}
        {verdict.scores && (
          <div>
            <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "var(--text-muted)", marginBottom: 10 }}>
              L12 SCORES
            </div>
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              <ScoreGauge label="WOLF" value={verdict.scores.wolf_score} />
              <ScoreGauge label="TII" value={verdict.scores.tii_score} />
              <ScoreGauge label="FRPC" value={verdict.scores.frpc_score} />
              {verdict.scores.confluence_score != null && (
                <ScoreGauge label="CONF" value={verdict.scores.confluence_score} />
              )}
              {verdict.scores.volume_profile_score != null && (
                <ScoreGauge label="VOL" value={verdict.scores.volume_profile_score} />
              )}
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
              {verdict.scores.regime && (
                <span className="badge badge-muted" style={{ fontSize: 9 }}>
                  {verdict.scores.regime}
                </span>
              )}
              {verdict.scores.session && (
                <span className="badge badge-muted" style={{ fontSize: 9 }}>
                  {verdict.scores.session}
                </span>
              )}
            </div>
          </div>
        )}

        {/* Gate checks */}
        {verdict.gates?.length > 0 && (
          <div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 10,
              }}
            >
              <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "var(--text-muted)" }}>
                GATE RATIONALE
              </div>
              <span
                style={{
                  fontSize: 10,
                  fontFamily: "var(--font-mono)",
                  color: passedGates === totalGates ? "var(--green)" : "var(--yellow)",
                }}
              >
                {passedGates}/{totalGates} passed
              </span>
            </div>
            <GateStatus gates={verdict.gates} />
          </div>
        )}

        {/* Pipeline (optional) */}
        <PipelineSection pair={verdict.symbol} />

        {/* Expiry */}
        {verdict.expires_at && (
          <div
            style={{
              padding: "8px 12px",
              background: "rgba(255,215,64,0.06)",
              border: "1px solid rgba(255,215,64,0.20)",
              borderRadius: "var(--radius-md)",
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <span style={{ fontSize: 10, color: "var(--yellow)", letterSpacing: "0.06em" }}>
              EXPIRES
            </span>
            <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-secondary)" }}>
              {new Date(verdict.expires_at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
          </div>
        )}
      </div>

      {/* Footer: no TAKE here — redirect to Signal Board */}
      <div
        style={{
          padding: "12px 16px",
          borderTop: "1px solid var(--border-default)",
          display: "flex",
          gap: 8,
          flexShrink: 0,
        }}
      >
        {isExecutable ? (
          <button
            onClick={() => router.push("/trades/signals")}
            style={{
              flex: 1,
              padding: "9px",
              borderRadius: "var(--radius-md)",
              background: "var(--accent)",
              border: "none",
              color: "#fff",
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: "0.07em",
              cursor: "pointer",
            }}
          >
            Execute on Signal Board
          </button>
        ) : (
          <div
            style={{
              flex: 1,
              padding: "9px",
              borderRadius: "var(--radius-md)",
              background: "var(--bg-elevated)",
              border: "1px solid var(--border-default)",
              textAlign: "center",
              fontSize: 10,
              color: "var(--text-muted)",
              letterSpacing: "0.06em",
            }}
          >
            Not executable — {String(verdict.verdict)}
          </div>
        )}
        <button
          onClick={onClose}
          style={{
            padding: "9px 14px",
            borderRadius: "var(--radius-md)",
            background: "transparent",
            border: "1px solid var(--border-strong)",
            color: "var(--text-muted)",
            fontSize: 11,
            cursor: "pointer",
          }}
        >
          Close
        </button>
      </div>
    </div>
  );
}
