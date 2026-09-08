/** Explicit browser response schemas. Never serialize arbitrary core diagnostics. */
const MAX_BODY_BYTES = 128 * 1024;
const MAX_SYMBOLS = 256;
const INGEST_STATES = ["HEALTHY", "DEGRADED", "NO_PRODUCER", "UNKNOWN"];
type RecordValue = Record<string, unknown>;

function record(value: unknown): RecordValue {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid projection");
  return value as RecordValue;
}

function choice(value: unknown, choices: readonly string[]): string | null {
  return typeof value === "string" && choices.includes(value) ? value : null;
}

function number(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1e12 ? value : null;
}

function boolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

export function projectStatus(value: unknown): RecordValue {
  const raw = record(value);
  const status = choice(raw.status, ["ok", "degraded", "unavailable", "error"]);
  if (!status) throw new Error("Invalid status projection");
  const result: RecordValue = {
    status,
    service: raw.service === "tuyul-fx" ? "tuyul-fx" : null,
    version: typeof raw.version === "string" && /^\d{1,4}\.\d{1,4}\.\d{1,4}$/.test(raw.version) ? raw.version : null,
    feed_status: choice(raw.feed_status, ["config_error", "no_transport", "no_producer", "fresh", "stale_preserved"]),
    freshness_class: choice(raw.freshness_class, ["LIVE", "DEGRADED_BUT_REFRESHING", "STALE_PRESERVED", "NO_PRODUCER", "NO_TRANSPORT", "CONFIG_ERROR"]),
    ingest_health: choice(raw.ingest_health, INGEST_STATES),
  };
  for (const key of ["feed_staleness_seconds", "feed_threshold_seconds", "feed_last_seen_ts", "producer_heartbeat_age_seconds", "engine_heartbeat_age_seconds", "orchestrator_heartbeat_age_seconds"]) result[key] = number(raw[key]);
  for (const key of ["redis_connected", "producer_alive", "engine_alive", "orchestrator_alive", "router_boot_ok"]) result[key] = boolean(raw[key]);
  return result;
}

export function projectHealth(value: unknown): RecordValue {
  const raw = record(value);
  if (raw.status !== "alive" || raw.service !== "tuyul-fx") throw new Error("Invalid health projection");
  return { status: "alive", service: "tuyul-fx" };
}

export function projectFeed(value: unknown): RecordValue {
  const raw = record(value);
  const ingest = choice(raw.ingest_status, INGEST_STATES);
  if (!ingest) throw new Error("Invalid feed projection");
  const entries = Object.entries(record(raw.symbols));
  if (entries.length > MAX_SYMBOLS) throw new Error("Oversized feed projection");
  const symbols: RecordValue = Object.create(null);
  for (const [symbol, value] of entries) {
    if (!/^[A-Z][A-Z0-9._-]{2,19}$/.test(symbol)) continue;
    const item = record(value);
    symbols[symbol] = {
      feed_status: choice(item.feed_status, ["LIVE", "DEGRADED", "STALE", "NO_DATA"]),
      age_seconds: number(item.age_seconds),
    };
  }
  return { ingest_status: ingest, provider_connected: boolean(raw.provider_connected), symbols };
}

async function readJson(response: Response): Promise<unknown> {
  if (!response.ok || response.redirected || !response.headers.get("content-type")?.toLowerCase().includes("application/json")) throw new Error("Upstream unavailable");
  if (Number(response.headers.get("content-length")) > MAX_BODY_BYTES || !response.body) throw new Error("Oversized response");
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let size = 0;
  let text = "";
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      size += chunk.value.byteLength;
      if (size > MAX_BODY_BYTES) throw new Error("Oversized response");
      text += decoder.decode(chunk.value, { stream: true });
    }
    text += decoder.decode();
    return JSON.parse(text);
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

export async function fetchViewerProjection(origin: string, path: string, token: string, requestId: string): Promise<RecordValue> {
  const signal = AbortSignal.timeout(5000);
  const read = async (corePath: string): Promise<unknown> => readJson(await fetch(origin + corePath, {
    method: "GET",
    headers: new Headers({ accept: "application/json", authorization: "Bearer " + token, "x-request-id": requestId }),
    cache: "no-store",
    redirect: "error",
    signal,
  }));
  if (path === "dashboard/overview") {
    const [status, health] = await Promise.all([read("/api/v1/status"), read("/healthz")]);
    return { status: projectStatus(status), health: projectHealth(health), source: "core-api" };
  }
  if (path === "dashboard/feed-status") return { ...projectFeed(await read("/api/v1/candles/feed-status")), source: "core-api" };
  if (path === "dashboard/aggregated-status") return { core_status: projectStatus(await read("/api/v1/status")), source: "core-api" };
  throw new Error("Unknown projection");
}
