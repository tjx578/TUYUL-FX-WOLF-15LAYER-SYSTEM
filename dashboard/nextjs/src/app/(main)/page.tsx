"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { VIEWER_ENDPOINTS } from "@/lib/viewerContract";
import RailwayDashboard from "@/components/wolf15-v2/RailwayDashboard";
import type { DashboardSnapshot, Observation } from "@/components/wolf15-v2/contracts";

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

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stringField(...values: unknown[]): string | null {
  const value = values.find((candidate) => typeof candidate === "string" && candidate.trim());
  return typeof value === "string" ? value : null;
}

function numberField(...values: unknown[]): number | null {
  const value = values.find((candidate) => typeof candidate === "number" && Number.isFinite(candidate));
  return typeof value === "number" ? value : null;
}

function safeJson(value: unknown): string {
  try {
    return JSON.stringify(
      value,
      (key, item) => /token|secret|password|authorization|cookie|api[_-]?key|dsn/i.test(key)
        ? "[REDACTED]"
        : item,
      2,
    ) ?? "null";
  } catch {
    return "Payload could not be rendered.";
  }
}

function emptyObservation<T>(): Observation<T> {
  return {
    state: "not_measured",
    data: null,
    asOf: null,
    source: null,
    requestId: null,
    freshness: { state: "NOT_MEASURED", policyId: null },
  };
}

function responseObservation<T>(
  probeState: ProbeState | undefined,
  data: T | null,
  options: { asOf?: string | null; source?: string | null } = {},
): Observation<T> {
  if (!probeState || probeState.state === "loading") return emptyObservation<T>();
  if (probeState.state === "error") {
    return {
      ...emptyObservation<T>(),
      state: "error",
      requestId: probeState.requestId ?? null,
      source: options.source ?? null,
    };
  }
  return {
    ...emptyObservation<T>(),
    state: "ready",
    data,
    asOf: options.asOf ?? null,
    source: options.source ?? probeState.path,
    requestId: probeState.requestId ?? null,
  };
}

async function probe(endpoint: (typeof VIEWER_ENDPOINTS)[number]): Promise<ProbeState> {
  try {
    const response = await fetch("/api/proxy/" + endpoint.path, {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      headers: { accept: "application/json" },
    });

    if (response.status === 401 || response.status === 403) {
      window.location.assign("/login");
      return { ...endpoint, state: "error", status: response.status };
    }

    if (!response.ok) {
      return {
        ...endpoint,
        state: "error",
        status: response.status,
        requestId: response.headers.get("x-request-id") || undefined,
        cache: response.headers.get("x-bff-cache") || undefined,
      };
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      return {
        ...endpoint,
        state: "error",
        status: response.status,
        requestId: response.headers.get("x-request-id") || undefined,
        cache: response.headers.get("x-bff-cache") || undefined,
      };
    }

    return {
      ...endpoint,
      state: "ok",
      status: response.status,
      requestId: response.headers.get("x-request-id") || undefined,
      cache: response.headers.get("x-bff-cache") || undefined,
      payload,
    };
  } catch {
    return { ...endpoint, state: "error" };
  }
}

function EvidencePanels({ probes }: { probes: ProbeState[] }) {
  return (
    <div style={{ display: "grid", gap: 12 }}>
      {probes.map((item) => (
        <article
          key={item.path}
          data-testid={`viewer-probe-${item.path}`}
          style={{
            border: "1px solid #20343c",
            borderRadius: 12,
            background: "#0c181d",
            color: "#eef8fa",
            overflow: "hidden",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: 14 }}>
            <div>
              <strong>{item.label}</strong>
              <div style={{ marginTop: 4, color: "#91a7af", fontSize: 12 }}>{item.description}</div>
            </div>
            <span style={{ color: item.state === "ok" ? "#59e391" : item.state === "error" ? "#ff6b78" : "#ffbf5b" }}>
              {item.state.toUpperCase()}{item.status ? ` · ${item.status}` : ""}
            </span>
          </div>
          <div style={{ borderTop: "1px solid #20343c", padding: 14, color: "#91a7af", fontSize: 11 }}>
            <span>{item.path}</span>
            <span style={{ marginLeft: 16 }}>CACHE {item.cache || "NOT_MEASURED"}</span>
            <span style={{ marginLeft: 16 }}>ID {item.requestId || "NOT_MEASURED"}</span>
          </div>
          {item.state === "ok" ? (
            <details style={{ borderTop: "1px solid #20343c", padding: 14 }}>
              <summary style={{ cursor: "pointer", color: "#3de0d0", fontSize: 11 }}>
                RAW PROJECTION EVIDENCE
              </summary>
              <pre style={{ overflow: "auto", color: "#cad9de", fontSize: 11, whiteSpace: "pre-wrap" }}>
                {safeJson(item.payload)}
              </pre>
            </details>
          ) : null}
        </article>
      ))}
    </div>
  );
}

function buildSnapshot(probes: ProbeState[], receivedAt: string | null, refreshing: boolean): DashboardSnapshot {
  const byPath = Object.fromEntries(probes.map((item) => [item.path, item]));
  const overviewProbe = byPath["dashboard/overview"];
  const feedProbe = byPath["dashboard/feed-status"];
  const aggregatedProbe = byPath["bff/aggregated-status"];

  const overviewPayload = asRecord(overviewProbe?.payload);
  const feedPayload = asRecord(feedProbe?.payload);
  const aggregatedPayload = asRecord(aggregatedProbe?.payload);
  const status = asRecord(overviewPayload.status);
  const coreStatus = asRecord(aggregatedPayload.core_status);
  const symbols = asRecord(feedPayload.symbols);
  const successfulReads = probes.filter((item) => item.state === "ok").length;
  const failedReads = probes.filter((item) => item.state === "error").length;

  const feedItems = Object.entries(symbols).map(([symbol, raw]) => {
    const item = asRecord(raw);
    return {
      symbol,
      provider: stringField(item.provider) ?? undefined,
      transport: stringField(item.transport) ?? undefined,
      state: stringField(item.feed_status, item.state) ?? undefined,
      quality: stringField(item.quality, item.feed_status) ?? undefined,
      lastEventAt: stringField(item.last_event_at, item.as_of) ?? undefined,
    };
  });

  const overviewAsOf = stringField(status.as_of, status.observed_at, overviewPayload.as_of);
  const feedAsOf = stringField(feedPayload.as_of, feedPayload.observed_at);
  const overviewData = {
    systemState: failedReads > 0 && successfulReads > 0
      ? "PARTIAL"
      : stringField(status.status, coreStatus.status),
    activeLifecycles: null,
    executionState: null,
    incidents: [],
  };
  const feedData = {
    connectionState: stringField(feedPayload.ingest_status, status.ingest_health, coreStatus.ingest_health),
    qualityState: stringField(status.freshness_class, status.feed_status, coreStatus.feed_status),
    candleGapCount: numberField(feedPayload.candle_gap_count),
    items: feedItems,
  };

  return {
    schemaVersion: "wolf15.ui.v2",
    connection: successfulReads > 0 ? "connected" : "not_connected",
    receivedAt,
    refreshing,
    identity: {
      environment: stringField(status.environment),
      mode: stringField(status.mode),
      strategyVersion: stringField(status.strategy_version),
      deploymentId: stringField(status.deployment_id),
      sha: stringField(status.sha, status.commit_sha),
    },
    overview: responseObservation(overviewProbe, overviewData, { asOf: overviewAsOf }),
    feed: responseObservation(feedProbe, feedData, { asOf: feedAsOf }),
    pairs: emptyObservation(),
    traces: emptyObservation(),
    risk: emptyObservation(),
    execution: emptyObservation(),
    audit: emptyObservation(),
    mcp: emptyObservation(),
    evidence: {
      overview: responseObservation(overviewProbe, overviewProbe?.payload ?? null, { asOf: overviewAsOf }),
      feedStatus: responseObservation(feedProbe, feedProbe?.payload ?? null, { asOf: feedAsOf }),
      aggregatedStatus: responseObservation(
        aggregatedProbe,
        aggregatedProbe?.payload ?? null,
        { asOf: stringField(aggregatedPayload.as_of, aggregatedPayload.observed_at) },
      ),
    },
  };
}

export default function DashboardPage() {
  const [probes, setProbes] = useState<ProbeState[]>(initialState);
  const [receivedAt, setReceivedAt] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setProbes((current) => current.map((item) => ({ ...item, state: "loading" })));
    const results = await Promise.all(VIEWER_ENDPOINTS.map(probe));
    setProbes(results);
    setReceivedAt(new Date().toISOString());
    setRefreshing(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const snapshot = useMemo(
    () => buildSnapshot(probes, receivedAt, refreshing),
    [probes, receivedAt, refreshing],
  );

  const logout = useCallback(async () => {
    setProbes(initialState);
    setReceivedAt(null);
    await fetch("/api/set-session", {
      method: "DELETE",
      credentials: "same-origin",
      cache: "no-store",
    }).catch(() => undefined);
    window.location.assign("/login");
  }, []);

  return (
    <RailwayDashboard
      snapshot={snapshot}
      existingEvidencePage={<EvidencePanels probes={probes} />}
      onRefresh={() => void refresh()}
      onLogout={() => void logout()}
    />
  );
}
