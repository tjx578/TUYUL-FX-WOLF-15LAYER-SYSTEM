import { describe, expect, it } from "vitest";
import { WsEventSchema } from "@/schema/wsEventSchema";

describe("WsEventSchema", () => {
  it("parses explicit ExecutionStateUpdated payload", () => {
    const parsed = WsEventSchema.parse({
      type: "ExecutionStateUpdated",
      payload: {
        execution_state: "FILLED",
        trade: {
          trade_id: "T-001",
          account_id: "ACC-1",
          symbol: "EURUSD",
          side: "BUY",
          lot: 0.1,
        },
      },
    });

    expect(parsed.type).toBe("ExecutionStateUpdated");
    if (parsed.type === "ExecutionStateUpdated") {
      expect(parsed.payload.trade.trade_id).toBe("T-001");
    }
  });

  it("parses SystemStatusUpdated payload", () => {
    const parsed = WsEventSchema.parse({
      type: "SystemStatusUpdated",
      payload: {
        mode: "DEGRADED",
        reason: "Redis stream lag",
      },
    });

    expect(parsed.type).toBe("SystemStatusUpdated");
    if (parsed.type === "SystemStatusUpdated") {
      expect(parsed.payload.mode).toBe("DEGRADED");
      expect(parsed.payload.reason).toBe("Redis stream lag");
    }
  });

  it("parses domain event types mapped from backend", () => {
    // Each type has a different required payload shape — provide correct fields per type.
    const cases: Array<{ type: string; payload: Record<string, unknown> }> = [
      { type: "SignalUpdated", payload: { symbol: "EURUSD" } },
      { type: "TradeSnapshot", payload: { symbol: "EURUSD" } },
      { type: "TradeUpdated", payload: { symbol: "EURUSD" } },
      {
        type: "CandleSnapshot",
        payload: {
          symbol: "EURUSD",
          candles: [
            { symbol: "EURUSD", timeframe: "M1", open: 1.1, high: 1.2, low: 1.0, close: 1.15, timestamp: 1700000000 },
          ],
        },
      },
      {
        type: "CandleForming",
        payload: { symbol: "EURUSD", timeframe: "M1", open: 1.1, high: 1.2, low: 1.0, close: 1.15, timestamp: 1700000000 },
      },
      {
        type: "EquityUpdated",
        payload: { timestamp: 1700000000, equity: 10000, balance: 9800, daily_dd: -1.5, total_dd: -2.0 },
      },
    ];

    for (const { type, payload } of cases) {
      const result = WsEventSchema.safeParse({ type, payload });
      expect(result.success, `${type} should parse successfully`).toBe(true);
      if (result.success) {
        expect(result.data.type).toBe(type);
      }
    }
  });

  it("rejects unknown event type with safeParse", () => {
    const result = WsEventSchema.safeParse({
      type: "SomeFutureEvent",
      payload: {},
    });
    expect(result.success).toBe(false);
  });
});
