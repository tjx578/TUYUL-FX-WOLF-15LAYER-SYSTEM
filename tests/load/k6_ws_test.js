/**
 * TUYUL FX Wolf-15 — WebSocket Load Test (k6)
 *
 * Scenarios:
 *   1. ws_concurrent  — 200 simultaneous WS clients sustaining for 60s
 *   2. tick_burst     — HTTP ingest endpoint flooded with 200 ticks/sec
 *   3. reconnect_storm — 100 rapid connect/disconnect cycles per second
 *
 * Prerequisites:
 *   brew install k6   (macOS)   |   choco install k6   (Windows)
 *
 * Run:
 *   k6 run tests/load/k6_ws_test.js \
 *     -e BASE_URL=https://api.yourdomain.com \
 *     -e WS_URL=wss://api.yourdomain.com/ws \
 *     -e TOKEN=<jwt>
 *
 * Success criteria (SLOs):
 *   p(95) WS round-trip latency   < 200 ms
 *   p(99) WS round-trip latency   < 500 ms
 *   WS dropped connections        < 1 %
 *   HTTP p(95) tick ingest        < 100 ms
 */

import ws from "k6/ws";
import http from "k6/http";
import { check, sleep } from "k6";
import { Counter, Trend, Rate } from "k6/metrics";

// ── Custom metrics ─────────────────────────────────────────────────────────

const wsLatency = new Trend("ws_latency_ms", true);
const wsDropped = new Rate("ws_dropped_connections");
const tickLatency = new Trend("tick_ingest_latency_ms", true);
const reconnectSucceeded = new Rate("ws_reconnect_succeeded");
const tickRejected = new Counter("tick_rejected_total");

// ── Env / config ──────────────────────────────────────────────────────────

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const WS_URL   = __ENV.WS_URL   || "ws://localhost:8000/ws";
const TOKEN    = __ENV.TOKEN    || "";

function wsUrlWithToken(path) {
  const url = `${WS_URL}${path}`;
  return TOKEN ? `${url}?token=${TOKEN}` : url;
}

function authHeaders() {
  return TOKEN
    ? { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" }
    : { "Content-Type": "application/json" };
}

// ── Scenarios ─────────────────────────────────────────────────────────────

export const options = {
  scenarios: {
    // 200 concurrent WS clients, each subscribed for 60 s
    ws_concurrent: {
      executor: "constant-vus",
      vus: 200,
      duration: "60s",
      exec: "wsScenario",
    },
    // Surge of 200 ticks/sec over 30 s
    tick_burst: {
      executor: "constant-arrival-rate",
      rate: 200,
      timeUnit: "1s",
      duration: "30s",
      preAllocatedVUs: 50,
      maxVUs: 100,
      exec: "tickIngestScenario",
      startTime: "5s",
    },
    // 100 rapid reconnects/sec for 20 s
    reconnect_storm: {
      executor: "constant-arrival-rate",
      rate: 100,
      timeUnit: "1s",
      duration: "20s",
      preAllocatedVUs: 50,
      maxVUs: 150,
      exec: "reconnectScenario",
      startTime: "10s",
    },
  },
  thresholds: {
    ws_latency_ms:              ["p(95)<200", "p(99)<500"],
    ws_dropped_connections:     ["rate<0.01"],
    tick_ingest_latency_ms:     ["p(95)<100"],
    ws_reconnect_succeeded:     ["rate>0.95"],
  },
};

// ── WS subscribe scenario ─────────────────────────────────────────────────

export function wsScenario() {
  const url = wsUrlWithToken("/prices");
  let dropped = false;
  let messageCount = 0;

  const res = ws.connect(url, {}, function (socket) {
    socket.on("open", () => {
      socket.send(JSON.stringify({ type: "subscribe", channel: "prices" }));
    });

    socket.on("message", (msg) => {
      messageCount++;
      try {
        const payload = JSON.parse(msg);
        const now = Date.now();
        const ts = payload?.timestamp_ms || now;
        wsLatency.add(now - ts);
      } catch (_) {
        // ignore non-JSON frames
      }
    });

    socket.on("error", () => {
      dropped = true;
    });

    socket.on("close", () => {
      wsDropped.add(dropped ? 1 : 0);
    });

    socket.setTimeout(() => socket.close(), 55_000);
  });

  check(res, { "WS status 101": (r) => r && r.status === 101 });
}

// ── Tick ingest scenario ───────────────────────────────────────────────────

export function tickIngestScenario() {
  const pairs = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "USDCHF"];
  const pair  = pairs[Math.floor(Math.random() * pairs.length)];
  const price = +(1.0 + Math.random() * 0.5).toFixed(5);

  const payload = JSON.stringify({
    symbol:    pair,
    bid:       price,
    ask:       price + 0.0002,
    timestamp: new Date().toISOString(),
  });

  const start = Date.now();
  const res = http.post(
    `${BASE_URL}/api/v1/ingest/tick`,
    payload,
    { headers: authHeaders() }
  );
  tickLatency.add(Date.now() - start);

  const ok = check(res, {
    "tick accepted (2xx)": (r) => r.status >= 200 && r.status < 300,
    "not rate limited":    (r) => r.status !== 429,
  });

  if (res.status === 429) {
    tickRejected.add(1);
  }
}

// ── Reconnect storm scenario ────────────────────────────────────────────────

export function reconnectScenario() {
  const url = wsUrlWithToken("/prices");
  let connected = false;

  ws.connect(url, {}, function (socket) {
    socket.on("open", () => {
      connected = true;
      socket.close();
    });

    socket.on("error", () => {
      connected = false;
    });

    socket.setTimeout(() => socket.close(), 3_000);
  });

  reconnectSucceeded.add(connected ? 1 : 0);
  sleep(0.01); // yield between iterations
}
