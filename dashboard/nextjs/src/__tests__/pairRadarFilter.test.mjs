import { describe, expect, it } from "vitest";
import { filterPairs } from "@/components/wolf15-v2/model.mjs";

// Pair Radar filters the canonical core verdict states. WAIT is not one of them,
// so the tab it used to serve could never match a projected row.
const rows = [
  { symbol: "EURUSD", lifecycleState: "HOLD", quality: "LIVE" },
  { symbol: "GBPUSD", lifecycleState: "NO_TRADE", quality: "LIVE" },
  { symbol: "USDJPY", lifecycleState: "EXECUTE_BUY", quality: "STALE" },
  { symbol: "XAUUSD", lifecycleState: "EXECUTE", quality: "LIVE" },
  { symbol: "AUDUSD", lifecycleState: "ABORT", quality: "LIVE" },
];

const symbols = (filter, query = "") => filterPairs(rows, query, filter).map((row) => row.symbol);

describe("Pair Radar verdict filter", () => {
  it("shows a HOLD row under the HOLD filter", () => {
    expect(symbols("hold")).toEqual(["EURUSD"]);
  });

  it("hides NO_TRADE and every EXECUTE state under the HOLD filter", () => {
    for (const hidden of ["GBPUSD", "USDJPY", "XAUUSD", "AUDUSD"]) {
      expect(symbols("hold")).not.toContain(hidden);
    }
  });

  it("keeps every row under the all filter", () => {
    expect(symbols("all")).toEqual(["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "AUDUSD"]);
  });

  it("matches the verdict exactly rather than by prefix", () => {
    const prefixed = [{ symbol: "NZDUSD", lifecycleState: "HOLDING", quality: "LIVE" }];
    expect(filterPairs(prefixed, "", "hold")).toEqual([]);
  });

  it("leaves the other filters on their own states", () => {
    expect(symbols("no-trade")).toEqual(["GBPUSD"]);
    expect(symbols("stale")).toEqual(["USDJPY"]);
  });

  it("still applies the search query inside a filter", () => {
    expect(symbols("hold", "eur")).toEqual(["EURUSD"]);
    expect(symbols("hold", "gbp")).toEqual([]);
  });
});
