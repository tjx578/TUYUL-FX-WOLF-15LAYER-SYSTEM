"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { VIEWER_ENDPOINTS } from "@/lib/viewerContract";

type ProbeState = {
  path: string;
  label: string;
  description: string;
  state: "loading" | "ok" | "error";
  status?: number;
  requestId?: string;
  cache?: string;
  payload?: unknown;
};

const initialState: ProbeState[] = VIEWER_ENDPOINTS.map((endpoint) => ({
  ...endpoint,
  state: "loading",
}));

async function probe(
  endpoint: (typeof VIEWER_ENDPOINTS)[number],
): Promise<ProbeState> {
  try {
    const response = await fetch("/api/proxy/" + endpoint.path, {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      headers: { accept: "application/json" },
    });

    if (response.status === 401) {
      window.location.assign("/login");
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      payload = { error: "Response was not valid JSON" };
    }

    return {
      ...endpoint,
      state: response.ok ? "ok" : "error",
      status: response.status,
      requestId: response.headers.get("x-request-id") || undefined,
      cache: response.headers.get("x-bff-cache") || undefined,
      payload,
    };
  } catch {
    return {
      ...endpoint,
      state: "error",
      payload: { error: "Request could not reach the viewer proxy" },
    };
  }
}

function statusColor(state: ProbeState["state"]): string {
  if (state === "ok") return "#a3e635";
  if (state === "error") return "#f87171";
  return "#facc15";
}

function pretty(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "{\"error\":\"Payload could not be rendered\"}";
  }
}

export default function DashboardPage() {
  const [probes, setProbes] = useState<ProbeState[]>(initialState);
  const [updatedAt, setUpdatedAt] = useState<string>("");
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setProbes((current) =>
      current.map((item) => ({ ...item, state: "loading" })),
    );
    const results = await Promise.all(VIEWER_ENDPOINTS.map(probe));
    setProbes(results);
    setUpdatedAt(new Date().toLocaleString());
    setRefreshing(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const summary = useMemo(() => {
    const ok = probes.filter((item) => item.state === "ok").length;
    if (ok === probes.length) return "CONNECTED";
    if (ok > 0) return "PARTIAL";
    if (probes.some((item) => item.state === "loading")) return "CHECKING";
    return "UNAVAILABLE";
  }, [probes]);

  async function logout() {
    await fetch("/api/set-session", {
      method: "DELETE",
      credentials: "same-origin",
      cache: "no-store",
    }).catch(() => undefined);
    window.location.assign("/login");
  }

  return (
    <main
      style={{
        width: "min(1480px, 100%)",
        boxSizing: "border-box",
        margin: "0 auto",
        padding: "clamp(20px, 4vw, 48px)",
      }}
    >
      <section
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: 18,
          marginBottom: 24,
        }}
      >
        <div>
          <div
            style={{
              color: statusColor(
                summary === "CONNECTED"
                  ? "ok"
                  : summary === "CHECKING"
                    ? "loading"
                    : "error",
              ),
              fontSize: 11,
              fontWeight: 900,
              letterSpacing: "0.14em",
            }}
          >
            {summary}
          </div>
          <h1
            style={{
              margin: "8px 0 6px",
              color: "#f8fafc",
              fontSize: "clamp(25px, 4vw, 42px)",
              letterSpacing: "-0.04em",
            }}
          >
            Live operational evidence
          </h1>
          <p
            style={{
              maxWidth: 720,
              margin: 0,
              color: "#94a3b8",
              fontSize: 13,
              lineHeight: 1.65,
            }}
          >
            Data below comes only from three authenticated GET projections on
            the dashboard BFF. No control or execution endpoint is exposed.
          </p>
          {updatedAt ? (
            <p style={{ margin: "8px 0 0", color: "#64748b", fontSize: 11 }}>
              Last refreshed {updatedAt}
            </p>
          ) : null}
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={refreshing}
            style={{
              border: "1px solid #3f4a5a",
              borderRadius: 9,
              background: "#111827",
              color: "#e2e8f0",
              cursor: refreshing ? "wait" : "pointer",
              padding: "10px 14px",
              fontSize: 11,
              fontWeight: 800,
            }}
          >
            {refreshing ? "REFRESHING" : "REFRESH"}
          </button>
          <button
            type="button"
            onClick={() => void logout()}
            style={{
              border: "1px solid #3f4a5a",
              borderRadius: 9,
              background: "transparent",
              color: "#94a3b8",
              cursor: "pointer",
              padding: "10px 14px",
              fontSize: 11,
              fontWeight: 800,
            }}
          >
            LOG OUT
          </button>
        </div>
      </section>

      <section
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 360px), 1fr))",
          gap: 16,
        }}
      >
        {probes.map((item) => (
          <article
            key={item.path}
            data-testid={"viewer-probe-" + item.path}
            style={{
              minWidth: 0,
              border: "1px solid rgba(148,163,184,0.18)",
              borderRadius: 16,
              background: "#0f172a",
              boxShadow: "0 18px 44px rgba(0,0,0,0.20)",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 12,
                borderBottom: "1px solid rgba(148,163,184,0.13)",
                padding: "16px 18px",
              }}
            >
              <div>
                <h2
                  style={{
                    margin: 0,
                    color: "#f8fafc",
                    fontSize: 15,
                  }}
                >
                  {item.label}
                </h2>
                <p
                  style={{
                    margin: "6px 0 0",
                    color: "#64748b",
                    fontSize: 11,
                    lineHeight: 1.5,
                  }}
                >
                  {item.description}
                </p>
              </div>
              <span
                style={{
                  alignSelf: "flex-start",
                  border: "1px solid " + statusColor(item.state) + "55",
                  borderRadius: 999,
                  color: statusColor(item.state),
                  padding: "4px 8px",
                  fontSize: 9,
                  fontWeight: 900,
                  letterSpacing: "0.1em",
                }}
              >
                {item.state.toUpperCase()}
                {item.status ? " · " + item.status : ""}
              </span>
            </div>

            <div
              style={{
                display: "flex",
                gap: 12,
                minHeight: 18,
                padding: "10px 18px 0",
                color: "#64748b",
                fontSize: 9,
                overflow: "hidden",
              }}
            >
              <span>{item.path}</span>
              {item.cache ? <span>CACHE {item.cache}</span> : null}
              {item.requestId ? (
                <span
                  title={item.requestId}
                  style={{
                    marginLeft: "auto",
                    maxWidth: 120,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  ID {item.requestId}
                </span>
              ) : null}
            </div>

            <pre
              style={{
                maxHeight: 420,
                margin: 0,
                overflow: "auto",
                padding: 18,
                color: item.state === "error" ? "#fecaca" : "#cbd5e1",
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                fontSize: 11,
                lineHeight: 1.55,
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              {item.state === "loading"
                ? "Waiting for authenticated BFF response..."
                : pretty(item.payload)}
            </pre>
          </article>
        ))}
      </section>
    </main>
  );
}
