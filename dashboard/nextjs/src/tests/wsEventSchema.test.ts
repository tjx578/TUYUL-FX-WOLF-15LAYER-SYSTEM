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
});
