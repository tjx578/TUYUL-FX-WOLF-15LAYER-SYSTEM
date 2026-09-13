/** Explicit browser response schemas. Never serialize arbitrary core diagnostics. */
const MAX_BODY_BYTES = 128 * 1024;
/** A verdict snapshot carries one entry per configured pair, so it needs a wider budget than the scalar status reads. */
const MAX_PAIR_BODY_BYTES = 1024 * 1024;
const MAX_SYMBOLS = 256;
const SYMBOL_PATTERN = /^[A-Z][A-Z0-9._-]{2,19}$/;
const INGEST_STATES = ["HEALTHY", "DEGRADED", "NO_PRODUCER", "UNKNOWN"];
const VERDICT_MODES = ["LIVE", "DEGRADED", "NO_SNAPSHOT_YET"];
const VERDICT_STATES = ["EXECUTE_BUY", "EXECUTE_SELL", "EXECUTE_REDUCED_RISK_BUY", "EXECUTE_REDUCED_RISK_SELL", "HOLD", "NO_TRADE", "WAIT"];
const ADMISSION_STATES = ["ALLOW", "HOLD", "BLOCK", "UNKNOWN"];
/** Mirrors the core verdict staleness threshold; quality is derived, never copied from upstream. */
const VERDICT_STALE_THRESHOLD_SECONDS = 300;
type RecordValue = Record<string, unknown>;

function record(value: unknown): RecordValue {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid projection");
  return value as RecordValue;
}

/** Optional nested blocks are absent on many verdicts; a missing block is NOT_MEASURED, never an error. */
function optionalRecord(value: unknown): RecordValue {
  return !value || typeof value !== "object" || Array.isArray(value) ? Object.create(null) : (value as RecordValue);
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

/** Core reports verdict snapshot time as epoch seconds; the browser contract is an ISO instant. */
function isoTimestamp(value: unknown): string | null {
  const seconds = number(value);
  return seconds === null || seconds < 1e9 ? null : new Date(seconds * 1000).toISOString();
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
    if (!SYMBOL_PATTERN.test(symbol)) continue;
    const item = record(value);
    symbols[symbol] = {
      feed_status: choice(item.feed_status, ["LIVE", "DEGRADED", "STALE", "NO_DATA"]),
      age_seconds: number(item.age_seconds),
    };
  }
  return { ingest_status: ingest, provider_connected: boolean(raw.provider_connected), symbols };
}

export function projectPairStates(value: unknown): RecordValue {
  const raw = record(value);
  const mode = choice(raw.mode, VERDICT_MODES);
  if (!mode) throw new Error("Invalid pair projection");
  const entries = Object.entries(record(raw.verdicts));
  if (entries.length > MAX_SYMBOLS) throw new Error("Oversized pair projection");
  const items: RecordValue[] = [];
  for (const [symbol, entry] of entries) {
    if (!SYMBOL_PATTERN.test(symbol)) continue;
    const item = optionalRecord(entry);
    const age = number(optionalRecord(item._meta).age_seconds);
    items.push({
      symbol,
      lifecycle_state: choice(item.verdict, VERDICT_STATES),
      admission: choice(optionalRecord(item.governance).action, ADMISSION_STATES),
      age_seconds: age,
      quality: age === null ? null : age <= VERDICT_STALE_THRESHOLD_SECONDS ? "LIVE" : "STALE",
    });
  }
  items.sort((left, right) => String(left.symbol).localeCompare(String(right.symbol)));
  return { mode, stale_seconds: number(raw.stale_seconds), observed_at: isoTimestamp(raw.timestamp), count: items.length, items };
}

async function readJson(response: Response, limit: number): Promise<unknown> {
  if (!response.ok || response.redirected || !response.headers.get("content-type")?.toLowerCase().includes("application/json")) throw new Error("Upstream unavailable");
  if (Number(response.headers.get("content-length")) > limit || !response.body) throw new Error("Oversized response");
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let size = 0;
  let text = "";
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      size += chunk.value.byteLength;
      if (size > limit) throw new Error("Oversized response");
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
  const read = async (corePath: string, limit: number = MAX_BODY_BYTES): Promise<unknown> => readJson(await fetch(origin + corePath, {
    method: "GET",
    headers: new Headers({ accept: "application/json", authorization: "Bearer " + token, "x-request-id": requestId }),
    cache: "no-store",
    redirect: "error",
    signal,
  }), limit);
  if (path === "dashboard/overview") {
    const [status, health] = await Promise.all([read("/api/v1/status"), read("/healthz")]);
    return { status: projectStatus(status), health: projectHealth(health), source: "core-api" };
  }
  if (path === "dashboard/feed-status") return { ...projectFeed(await read("/api/v1/candles/feed-status")), source: "core-api" };
  if (path === "dashboard/aggregated-status") return { core_status: projectStatus(await read("/api/v1/status")), source: "core-api" };
  if (path === "dashboard/pair-states") return { ...projectPairStates(await read("/api/v1/verdict/all", MAX_PAIR_BODY_BYTES)), source: "core-api" };
  throw new Error("Unknown projection");
}
