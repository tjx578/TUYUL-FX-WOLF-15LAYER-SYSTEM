/**
 * TradeDeskTradeSchema Normalization Tests — PR-010
 *
 * Tests that the Zod schema correctly normalises backend field aliases
 * (symbol↔pair, side↔direction, lot↔lot_size) into canonical names.
 */
import { describe, expect, it } from "vitest";
import {
    TradeDeskTradeSchema,
    TradeDeskResponseSchema,
    TRADE_STATUSES,
    TERMINAL_STATUSES,
} from "@/features/trades/model/tradeDeskSchema";

describe("TradeDeskTradeSchema normalization", () => {
    it("normalizes 'symbol' to 'pair'", () => {
        const result = TradeDeskTradeSchema.parse({
            trade_id: "t-1",
            account_id: "acc-1",
            symbol: "EURUSD",
            status: "OPEN",
        });
        expect(result.pair).toBe("EURUSD");
    });

    it("prefers 'pair' over 'symbol' when both present", () => {
        const result = TradeDeskTradeSchema.parse({
            trade_id: "t-2",
            account_id: "acc-1",
            pair: "GBPUSD",
            symbol: "EURUSD",
            status: "OPEN",
        });
        expect(result.pair).toBe("GBPUSD");
    });

    it("normalizes 'side' to 'direction'", () => {
        const result = TradeDeskTradeSchema.parse({
            trade_id: "t-3",
            account_id: "acc-1",
            side: "BUY",
            status: "OPEN",
        });
        expect(result.direction).toBe("BUY");
    });

    it("prefers 'direction' over 'side' when both present", () => {
        const result = TradeDeskTradeSchema.parse({
            trade_id: "t-4",
            account_id: "acc-1",
            direction: "SELL",
            side: "BUY",
            status: "OPEN",
        });
        expect(result.direction).toBe("SELL");
    });

    it("normalizes 'lot' to 'lot_size'", () => {
        const result = TradeDeskTradeSchema.parse({
            trade_id: "t-5",
            account_id: "acc-1",
            lot: 0.1,
            status: "OPEN",
        });
        expect(result.lot_size).toBe(0.1);
    });

    it("prefers 'lot_size' over 'lot' when both present", () => {
        const result = TradeDeskTradeSchema.parse({
            trade_id: "t-6",
            account_id: "acc-1",
            lot_size: 0.5,
            lot: 0.1,
            status: "OPEN",
        });
        expect(result.lot_size).toBe(0.5);
    });

    it("passes through all other fields", () => {
        const result = TradeDeskTradeSchema.parse({
            trade_id: "t-7",
            signal_id: "sig-1",
            account_id: "acc-1",
            pair: "USDJPY",
            direction: "BUY",
            lot_size: 0.2,
            status: "CLOSED",
            entry_price: 150.0,
            stop_loss: 149.5,
            take_profit: 151.0,
            pnl: 100,
            opened_at: "2024-01-01T00:00:00Z",
            closed_at: "2024-01-01T12:00:00Z",
            close_reason: "TP_HIT",
        });

        expect(result.trade_id).toBe("t-7");
        expect(result.signal_id).toBe("sig-1");
        expect(result.entry_price).toBe(150.0);
        expect(result.stop_loss).toBe(149.5);
        expect(result.take_profit).toBe(151.0);
        expect(result.pnl).toBe(100);
        expect(result.close_reason).toBe("TP_HIT");
    });

    it("rejects empty trade_id", () => {
        const result = TradeDeskTradeSchema.safeParse({
            trade_id: "",
            account_id: "acc-1",
            status: "OPEN",
        });
        expect(result.success).toBe(false);
    });

    it("rejects empty account_id", () => {
        const result = TradeDeskTradeSchema.safeParse({
            trade_id: "t-1",
            account_id: "",
            status: "OPEN",
        });
        expect(result.success).toBe(false);
    });
});

describe("TRADE_STATUSES", () => {
    it("contains all 8 expected statuses", () => {
        expect(TRADE_STATUSES).toEqual([
            "INTENDED", "PENDING", "OPEN", "CLOSED",
            "CANCELLED", "SKIPPED", "PARTIALLY_FILLED", "REJECTED",
        ]);
    });
});

describe("TERMINAL_STATUSES", () => {
    it("contains only terminal statuses", () => {
        expect(TERMINAL_STATUSES).toEqual(["CLOSED", "CANCELLED", "SKIPPED", "REJECTED"]);
    });
});
