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

  it("parses PreferencesUpdated payload", () => {
    const parsed = WsEventSchema.parse({
      type: "PreferencesUpdated",
      payload: {
        density: "compact",
        showLatency: false,
        layoutPreset: "pipeline_focus",
      },
    });

    expect(parsed.type).toBe("PreferencesUpdated");
    if (parsed.type === "PreferencesUpdated") {
      expect(parsed.payload.layoutPreset).toBe("pipeline_focus");
    }
  });

  it("parses domain event types mapped from backend", () => {
    const types = [
      "SignalUpdated",
      "TradeSnapshot",
      "TradeUpdated",
      "CandleSnapshot",
      "CandleForming",
      "EquityUpdated",
    ] as const;

    for (const t of types) {
      const result = WsEventSchema.safeParse({
        type: t,
        payload: { symbol: "EURUSD" },
      });
      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.type).toBe(t);
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
