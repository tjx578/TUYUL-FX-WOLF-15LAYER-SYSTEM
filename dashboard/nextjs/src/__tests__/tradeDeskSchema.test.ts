/**
 * Unit tests for schema/tradeDeskSchema.ts
 *
 * Tests:
 *  - TRADE_STATUSES enum accepts known statuses
 *  - Status fallback accepts unknown status strings
 *  - Field alias normalization (symbol→pair, side→direction, lot→lot_size)
 *  - TERMINAL_STATUSES includes correct values
 *  - TradeDeskResponseSchema validation
 */

import { describe, it, expect } from "vitest";
import {
    TradeDeskTradeSchema,
    TradeDeskResponseSchema,
    TRADE_STATUSES,
    TERMINAL_STATUSES,
    type TradeStatus,
} from "@/schema/tradeDeskSchema";

// ══════════════════════════════════════════════════════════════
//  TRADE_STATUSES enum
// ══════════════════════════════════════════════════════════════

describe("TRADE_STATUSES", () => {
    it("should contain all 8 known statuses", () => {
        expect(TRADE_STATUSES).toEqual([
            "INTENDED", "PENDING", "OPEN", "CLOSED",
            "CANCELLED", "SKIPPED", "PARTIALLY_FILLED", "REJECTED",
        ]);
    });
});

describe("TERMINAL_STATUSES", () => {
    it("should include CLOSED, CANCELLED, SKIPPED, REJECTED", () => {
        expect(TERMINAL_STATUSES).toContain("CLOSED");
        expect(TERMINAL_STATUSES).toContain("CANCELLED");
        expect(TERMINAL_STATUSES).toContain("SKIPPED");
        expect(TERMINAL_STATUSES).toContain("REJECTED");
    });

    it("should NOT include active statuses", () => {
        expect(TERMINAL_STATUSES).not.toContain("OPEN");
        expect(TERMINAL_STATUSES).not.toContain("PENDING");
        expect(TERMINAL_STATUSES).not.toContain("INTENDED");
    });
});

// ══════════════════════════════════════════════════════════════
//  TradeDeskTradeSchema — Status validation
// ══════════════════════════════════════════════════════════════

describe("TradeDeskTradeSchema status validation", () => {
    const baseTrade = {
        trade_id: "T-001",
        account_id: "ACC-001",
        symbol: "EURUSD",
        side: "BUY" as const,
        lot: 0.1,
    };

    for (const status of TRADE_STATUSES) {
        it(`should accept known status: ${status}`, () => {
            const result = TradeDeskTradeSchema.safeParse({ ...baseTrade, status });
            expect(result.success).toBe(true);
        });
    }

    it("should accept unknown status via z.string() fallback", () => {
        const result = TradeDeskTradeSchema.safeParse({
            ...baseTrade,
            status: "SOME_FUTURE_STATUS",
        });
        expect(result.success).toBe(true);
        if (result.success) {
            expect(result.data.status).toBe("SOME_FUTURE_STATUS");
        }
    });

    it("should reject empty status string", () => {
        const result = TradeDeskTradeSchema.safeParse({
            ...baseTrade,
            status: "",
        });
        expect(result.success).toBe(false);
    });
});

// ══════════════════════════════════════════════════════════════
//  TradeDeskTradeSchema — Field alias normalization
// ══════════════════════════════════════════════════════════════

describe("TradeDeskTradeSchema field normalization", () => {
    it("should normalize symbol → pair", () => {
        const result = TradeDeskTradeSchema.parse({
            trade_id: "T-001",
            account_id: "ACC-001",
            symbol: "EURUSD",
            status: "OPEN",
        });
        expect(result.pair).toBe("EURUSD");
    });

    it("should prefer pair over symbol when both are present", () => {
        const result = TradeDeskTradeSchema.parse({
            trade_id: "T-001",
            account_id: "ACC-001",
            pair: "GBPUSD",
            symbol: "EURUSD",
            status: "OPEN",
        });
        expect(result.pair).toBe("GBPUSD");
    });

    it("should normalize side → direction", () => {
        const result = TradeDeskTradeSchema.parse({
            trade_id: "T-001",
            account_id: "ACC-001",
            side: "SELL",
            status: "OPEN",
        });
        expect(result.direction).toBe("SELL");
    });

    it("should normalize lot → lot_size", () => {
        const result = TradeDeskTradeSchema.parse({
            trade_id: "T-001",
            account_id: "ACC-001",
            lot: 0.5,
            status: "OPEN",
        });
        expect(result.lot_size).toBe(0.5);
    });

    it("should prefer lot_size over lot when both are present", () => {
        const result = TradeDeskTradeSchema.parse({
            trade_id: "T-001",
            account_id: "ACC-001",
            lot: 0.5,
            lot_size: 1.0,
            status: "OPEN",
        });
        expect(result.lot_size).toBe(1.0);
    });
});

// ══════════════════════════════════════════════════════════════
//  TradeDeskResponseSchema
// ══════════════════════════════════════════════════════════════

describe("TradeDeskResponseSchema", () => {
    it("should validate a complete desk response", () => {
        const response = {
            trades: {
                pending: [{ trade_id: "T-1", account_id: "A-1", status: "PENDING", symbol: "EURUSD" }],
                open: [],
                closed: [],
                cancelled: [],
            },
            exposure: {
                by_pair: [],
                by_account: [],
                total_lots: 0,
                total_trades: 1,
            },
            anomalies: [],
            counts: { pending: 1, open: 0, closed: 0, cancelled: 0, total: 1 },
            server_ts: Date.now() / 1000,
        };

        const result = TradeDeskResponseSchema.safeParse(response);
        expect(result.success).toBe(true);
    });

    it("should validate PARTIALLY_FILLED status in response", () => {
        const response = {
            trades: {
                pending: [],
                open: [{ trade_id: "T-1", account_id: "A-1", status: "PARTIALLY_FILLED", symbol: "EURUSD" }],
                closed: [],
                cancelled: [],
            },
            exposure: { by_pair: [], by_account: [], total_lots: 0, total_trades: 1 },
            anomalies: [],
            counts: { pending: 0, open: 1, closed: 0, cancelled: 0, total: 1 },
            server_ts: Date.now() / 1000,
        };

        const result = TradeDeskResponseSchema.safeParse(response);
        expect(result.success).toBe(true);
    });
});
