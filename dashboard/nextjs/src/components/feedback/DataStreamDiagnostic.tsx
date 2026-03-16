"use client";

// ============================================================
// TUYUL FX Wolf-15 — DataStreamDiagnostic
// Shown when one or more API streams fail.
// Per-stream status grid, /health ping, env checklist, retry.
// ============================================================

import { useState, useCallback } from "react";
import { mutate } from "swr";

interface DataStreamDiagnosticProps {
  failedStreams: string[];
  allStreams: string[];
}

const STREAM_ENDPOINTS: Record<string, string> = {
  verdicts:  "/api/v1/verdict/all",
  trades:    "/api/v1/trades/active",
  context:   "/api/v1/context",
  execution: "/api/v1/execution",
  accounts:  "/api/v1/accounts",
  risk:      "/api/v1/accounts/risk-snapshot",
};

const CHECKLIST = [
  {
    label: "INTERNAL_API_URL env var",
    detail: "Set INTERNAL_API_URL (server-side) on Vercel project Vars. Example: https://wolf15-api.up.railway.app — WITHOUT trailing /api",
    key: "env-url",
  },
  {
    label: "NEXT_PUBLIC_WS_BASE_URL env var",
    detail: "Set NEXT_PUBLIC_WS_BASE_URL to your Railway wss:// origin. Example: wss://wolf15-api.up.railway.app — required for Live Feed on Vercel.",
    key: "env-ws",
  },
  {
    label: "/health endpoint reachable",
    detail: "Backend must respond 200 at GET /health (no /api prefix). Check PING /health result above.",
    key: "health",
  },
  {
    label: "CORS_ORIGINS includes dashboard domain",
    detail: "Backend CORS config must allow the Vercel deployment URL and wss:// origin for WebSocket upgrades.",
    key: "cors",
  },
];

export default function DataStreamDiagnostic({
  failedStreams,
  allStreams,
}: DataStreamDiagnosticProps) {
  const [expanded, setExpanded] = useState(false);
  const [pinging, setPinging]   = useState(false);
  const [pingResult, setPingResult] = useState<{
    ok: boolean;
    latency?: number;
    status?: number;
    error?: string;
  } | null>(null);
  const [retrying, setRetrying] = useState(false);

  const handlePing = useCallback(async () => {
    setPinging(true);
    setPingResult(null);
    const t0 = performance.now();
    try {
      const res = await fetch("/health", { credentials: "include" });
      const latency = Math.round(performance.now() - t0);
      setPingResult({ ok: res.ok, latency, status: res.status });
    } catch (err) {
      const latency = Math.round(performance.now() - t0);
      setPingResult({ ok: false, latency, error: err instanceof Error ? err.message : "Network error" });
    } finally {
      setPinging(false);
    }
  }, []);

  const handleRetry = useCallback(async () => {
    setRetrying(true);
    try {
      await Promise.all(
        failedStreams.map((s) => {
          const ep = STREAM_ENDPOINTS[s];
          return ep ? mutate(ep) : Promise.resolve();
        })
      );
    } finally {
      setTimeout(() => setRetrying(false), 800);
    }
  }, [failedStreams]);

  return (
    <div
      role="alert"
      className="panel"
      style={{
        borderColor: "var(--border-danger)",
        background: "linear-gradient(135deg, rgba(255,61,87,0.06), rgba(11,22,35,0.0))",
        padding: "14px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      {/* ── Top row ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: "50%",
            background: "var(--red)",
            display: "inline-block",
            animation: "pulse-dot 1.2s ease-in-out infinite",
            flexShrink: 0,
          }}
        />
        <span style={{ fontFamily: "var(--font-display)", fontSize: 13, fontWeight: 800, color: "var(--red)", letterSpacing: "0.04em" }}>
          DATA STREAM ISSUE DETECTED
        </span>
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
          Failed: <span style={{ color: "var(--red)", fontWeight: 700 }}>{failedStreams.join(", ")}</span>
        </span>

        {/* Actions */}
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <button
            className="btn btn-ghost"
            style={{ fontSize: 10, padding: "4px 12px" }}
            onClick={handlePing}
            disabled={pinging}
            aria-label="Ping backend health endpoint"
          >
            {pinging ? "PINGING…" : "PING /health"}
          </button>
          <button
            className="btn btn-danger"
            style={{ fontSize: 10, padding: "4px 12px" }}
            onClick={handleRetry}
            disabled={retrying}
            aria-label="Retry failed streams"
          >
            {retrying ? "RETRYING…" : "RETRY"}
          </button>
          <button
            className="btn btn-ghost"
            style={{ fontSize: 10, padding: "4px 12px" }}
            onClick={() => setExpanded((p) => !p)}
            aria-expanded={expanded}
            aria-label="Toggle diagnostic details"
          >
            {expanded ? "HIDE DETAILS" : "SHOW DETAILS"}
          </button>
        </div>
      </div>

      {/* ── Stream status grid ── */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {allStreams.map((stream) => {
          const failed = failedStreams.includes(stream);
          return (
            <div
              key={stream}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 5,
                padding: "3px 9px",
                borderRadius: "var(--radius-sm)",
                background: failed ? "var(--red-glow)" : "var(--green-glow)",
                border: `1px solid ${failed ? "var(--border-danger)" : "var(--border-success)"}`,
              }}
            >
              <span
                style={{
                  width: 5,
                  height: 5,
                  borderRadius: "50%",
                  background: failed ? "var(--red)" : "var(--green)",
                  display: "inline-block",
                }}
              />
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 700, color: failed ? "var(--red)" : "var(--green)" }}>
                {stream.toUpperCase()}
              </span>
            </div>
          );
        })}
      </div>

      {/* ── Ping result ── */}
      {pingResult && (
        <div
          className="animate-fade-in"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "7px 10px",
            borderRadius: "var(--radius-sm)",
            background: pingResult.ok ? "var(--green-glow)" : "var(--red-glow)",
            border: `1px solid ${pingResult.ok ? "var(--border-success)" : "var(--border-danger)"}`,
            fontSize: 11,
          }}
        >
          <span style={{ fontFamily: "var(--font-mono)", color: pingResult.ok ? "var(--green)" : "var(--red)", fontWeight: 700 }}>
            {pingResult.ok ? "ONLINE" : "OFFLINE"}
          </span>
          {pingResult.status && (
            <span style={{ color: "var(--text-muted)" }}>HTTP {pingResult.status}</span>
          )}
          {pingResult.latency != null && (
            <span style={{ color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>
              {pingResult.latency}ms
            </span>
          )}
          {pingResult.error && (
            <span style={{ color: "var(--red)" }}>{pingResult.error}</span>
          )}
        </div>
      )}

      {/* ── Expanded details: checklist ── */}
      {expanded && (
        <div className="animate-fade-in" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.12em", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
            DIAGNOSTIC CHECKLIST
          </div>
          {CHECKLIST.map(({ label, detail, key }) => (
            <div
              key={key}
              style={{
                display: "flex",
                gap: 10,
                padding: "8px 10px",
                background: "var(--bg-card)",
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--border-default)",
              }}
            >
              <span style={{ fontSize: 10, color: "var(--text-muted)", flexShrink: 0 }}>—</span>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-secondary)" }}>{label}</div>
                <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>{detail}</div>
              </div>
            </div>
          ))}
          <div style={{ fontSize: 10, color: "var(--text-faint)", marginTop: 4 }}>
            Go to Settings &rarr; Vars to update INTERNAL_API_URL on this Vercel project.
          </div>
        </div>
      )}
    </div>
  );
}
