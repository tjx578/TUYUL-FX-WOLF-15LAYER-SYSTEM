"use client";

import { useEffect, useState } from "react";
import { useSystemStore } from "@/store/useSystemStore";

// PRD requirement: stale indicator must appear within 5s of WS disconnect.
// Shows degraded mode banner, stale duration counter, and offline instructions.
export default function DegradationBanner() {
  const mode = useSystemStore((s) => s.mode);
  const wsStatus = useSystemStore((s) => s.wsStatus);
  const system = useSystemStore((s) => s.system);

  const [staleSince, setStaleSince] = useState<number | null>(null);
  const [staleSeconds, setStaleSeconds] = useState(0);
  const [dismissed, setDismissed] = useState(false);

  const reasonLower = system?.reason?.toLowerCase() ?? "";
  const isOffline =
    wsStatus === "DISCONNECTED" ||
    reasonLower.includes("unreachable") ||
    reasonLower.includes("offline") ||
    reasonLower.includes("econnrefused") ||
    reasonLower.includes("connection refused") ||
    reasonLower.includes("etimedout") ||
    reasonLower.includes("enetunreach");

  const isDegraded = mode === "DEGRADED" || wsStatus === "RECONNECTING" || wsStatus === "DISCONNECTED";

  // Track stale duration
  useEffect(() => {
    if (isDegraded && staleSince === null) {
      setStaleSince(Date.now());
      setDismissed(false);
    }
    if (!isDegraded) {
      setStaleSince(null);
      setStaleSeconds(0);
    }
  }, [isDegraded, staleSince]);

  useEffect(() => {
    if (staleSince === null) return;
    const interval = setInterval(() => {
      setStaleSeconds(Math.floor((Date.now() - staleSince) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [staleSince]);

  if (!isDegraded || dismissed) return null;

  const reason =
    system?.reason ||
    (wsStatus === "RECONNECTING"
      ? "Live channel reconnecting — data may be stale."
      : wsStatus === "DISCONNECTED"
        ? "Backend connection lost — operating with last known data."
        : "System reported degraded mode.");

  const staleLabel =
    staleSeconds < 60
      ? `${staleSeconds}s`
      : `${Math.floor(staleSeconds / 60)}m ${staleSeconds % 60}s`;

  return (
    <section
      role="alert"
      aria-live="assertive"
      style={{
        marginBottom: 12,
        borderRadius: "var(--radius-sm)",
        border: `1px solid ${isOffline ? "var(--border-danger)" : "var(--border-warn)"}`,
        background: isOffline ? "rgba(255,59,48,0.06)" : "rgba(255,215,64,0.06)",
        padding: "10px 14px",
        display: "flex",
        alignItems: "flex-start",
        gap: 12,
      }}
    >
      {/* Status dot */}
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: isOffline ? "var(--red)" : "var(--yellow)",
          flexShrink: 0,
          marginTop: 3,
          animation: "pulse-dot 1.5s ease-in-out infinite",
        }}
        aria-hidden="true"
      />

      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexWrap: "wrap",
          }}
        >
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              fontWeight: 800,
              letterSpacing: "0.08em",
              color: isOffline ? "var(--red)" : "var(--yellow)",
            }}
          >
            {isOffline ? "BACKEND OFFLINE" : "DEGRADED MODE"}
          </span>

          {/* Stale duration */}
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 9,
              color: "var(--text-muted)",
              padding: "2px 6px",
              borderRadius: 3,
              background: "rgba(255,255,255,0.05)",
            }}
          >
            STALE {staleLabel}
          </span>

          {/* WS status pill */}
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 9,
              color: wsStatus === "RECONNECTING" ? "var(--yellow)" : "var(--text-faint)",
              padding: "2px 6px",
              borderRadius: 3,
              border: "1px solid var(--border-default)",
            }}
          >
            WS {wsStatus}
          </span>
        </div>

        <p
          style={{
            fontSize: 11,
            color: "var(--text-secondary)",
            marginTop: 3,
            marginBottom: 0,
          }}
        >
          {reason}
        </p>

        {isOffline && (
          <p
            style={{
              fontSize: 10,
              color: "var(--text-muted)",
              marginTop: 4,
              marginBottom: 0,
              fontFamily: "var(--font-mono)",
            }}
          >
            Set{" "}
            <code
              style={{
                background: "rgba(255,255,255,0.07)",
                padding: "1px 4px",
                borderRadius: 3,
              }}
            >
              NEXT_PUBLIC_API_BASE_URL
            </code>{" "}
            and{" "}
            <code
              style={{
                background: "rgba(255,255,255,0.07)",
                padding: "1px 4px",
                borderRadius: 3,
              }}
            >
              NEXT_PUBLIC_WS_URL
            </code>{" "}
            to connect to your backend.
          </p>
        )}
      </div>

      {/* Dismiss */}
      <button
        onClick={() => setDismissed(true)}
        aria-label="Dismiss degradation banner"
        style={{
          background: "transparent",
          border: "none",
          cursor: "pointer",
          color: "var(--text-faint)",
          fontSize: 14,
          lineHeight: 1,
          padding: "2px 4px",
          flexShrink: 0,
        }}
      >
        &times;
      </button>
    </section>
  );
}
