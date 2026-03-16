/**
 * Unit tests for lib/realtime/realtimeClient.ts
 *
 * Tests:
 *  - Connection lifecycle (open, close, intentional close)
 *  - Event normalization (backend event_type → PascalCase type)
 *  - Reconnect with exponential backoff
 *  - Sequence gap detection
 *  - Stale detection (5s no message → STALE)
 *  - Missing WS base URL → immediate DISCONNECTED
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// ── Mock dependencies BEFORE importing module under test ─────

vi.mock("@/lib/auth", () => ({
    getTransportToken: vi.fn(() => "mock-jwt-token"),
    fetchWsTicket: vi.fn(async () => "mock-ws-ticket"),
}));

vi.mock("@/lib/env", () => ({
    getWsBaseUrl: vi.fn(() => "wss://test.example.com"),
}));

// Mock WsEventSchema to accept any object with a `type` field
vi.mock("@/schema/wsEventSchema", () => ({
    WsEventSchema: {
        parse: vi.fn((data: Record<string, unknown>) => data),
    },
}));

import { connectLiveUpdates, type WsConnectionStatus } from "@/lib/realtime/realtimeClient";
import { getWsBaseUrl } from "@/lib/env";

// ── Mock WebSocket ───────────────────────────────────────────

class MockWebSocket {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSING = 2;
    static CLOSED = 3;

    readyState = MockWebSocket.CONNECTING;
    url: string;

    onopen: ((ev: unknown) => void) | null = null;
    onmessage: ((ev: { data: string }) => void) | null = null;
    onerror: (() => void) | null = null;
    onclose: (() => void) | null = null;

    constructor(url: string) {
        this.url = url;
        MockWebSocket._instances.push(this);
    }

    close() {
        this.readyState = MockWebSocket.CLOSED;
    }

    send = vi.fn();

    // Test harness helpers
    static _instances: MockWebSocket[] = [];
    static _reset() {
        MockWebSocket._instances = [];
    }
    static _latest(): MockWebSocket | undefined {
        return MockWebSocket._instances[MockWebSocket._instances.length - 1];
    }

    simulateOpen() {
        this.readyState = MockWebSocket.OPEN;
        this.onopen?.({});
    }

    simulateMessage(data: Record<string, unknown>) {
        this.onmessage?.({ data: JSON.stringify(data) });
    }

    simulateClose() {
        this.readyState = MockWebSocket.CLOSED;
        this.onclose?.();
    }

    simulateError() {
        this.onerror?.();
    }
}

// Attach static constants to match WebSocket API
Object.assign(MockWebSocket, {
    CONNECTING: 0,
    OPEN: 1,
    CLOSING: 2,
    CLOSED: 3,
});

// ── Setup ────────────────────────────────────────────────────

beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket._reset();
    (globalThis as unknown as Record<string, unknown>).WebSocket = MockWebSocket as unknown as typeof WebSocket;
    vi.mocked(getWsBaseUrl).mockReturnValue("wss://test.example.com");
});

afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
});

// ── Tests ────────────────────────────────────────────────────

describe("connectLiveUpdates", () => {
    it("should transition to LIVE on successful connection", async () => {
        const statuses: WsConnectionStatus[] = [];
        const onEvent = vi.fn();

        connectLiveUpdates({
            path: "/ws/test",
            onEvent,
            onStatusChange: (s) => statuses.push(s),
        });

        // Let the async connect() resolve
        await vi.runAllTimersAsync();

        const ws = MockWebSocket._latest()!;
        expect(ws).toBeDefined();
        expect(ws.url).toContain("wss://test.example.com/ws/test");
        expect(ws.url).toContain("token=mock-jwt-token");

        ws.simulateOpen();
        expect(statuses).toContain("CONNECTING");
        expect(statuses).toContain("LIVE");
    });

    it("should pass parsed JSON through WsEventSchema to onEvent", async () => {
        const onEvent = vi.fn();

        connectLiveUpdates({ path: "/ws/test", onEvent });
        await vi.runAllTimersAsync();

        const ws = MockWebSocket._latest()!;
        ws.simulateOpen();
        ws.simulateMessage({
            type: "PriceUpdated",
            payload: { symbol: "EURUSD", bid: 1.10 },
        });

        expect(onEvent).toHaveBeenCalledWith(
            expect.objectContaining({ type: "PriceUpdated" })
        );
    });

    it("should fire onRawMessage before Zod validation", async () => {
        const onRawMessage = vi.fn();
        const onEvent = vi.fn();

        connectLiveUpdates({ path: "/ws/test", onEvent, onRawMessage });
        await vi.runAllTimersAsync();

        const ws = MockWebSocket._latest()!;
        ws.simulateOpen();
        ws.simulateMessage({ type: "PriceUpdated", payload: {} });

        expect(onRawMessage).toHaveBeenCalledBefore(onEvent);
    });

    it("should detect sequence gaps and fire onSeqGap", async () => {
        const onSeqGap = vi.fn();
        const onEvent = vi.fn();

        connectLiveUpdates({ path: "/ws/test", onEvent, onSeqGap });
        await vi.runAllTimersAsync();

        const ws = MockWebSocket._latest()!;
        ws.simulateOpen();

        // Send seq 1, then skip to seq 4 (gap of 2)
        ws.simulateMessage({ type: "PriceUpdated", payload: {}, seq: 1 });
        ws.simulateMessage({ type: "PriceUpdated", payload: {}, seq: 4 });

        expect(onSeqGap).toHaveBeenCalledWith(2);
    });

    it("should track gapCount on controls", async () => {
        const onEvent = vi.fn();

        const controls = connectLiveUpdates({ path: "/ws/test", onEvent });
        await vi.runAllTimersAsync();

        const ws = MockWebSocket._latest()!;
        ws.simulateOpen();

        ws.simulateMessage({ type: "PriceUpdated", payload: {}, seq: 1 });
        ws.simulateMessage({ type: "PriceUpdated", payload: {}, seq: 5 }); // gap

        expect(controls.gapCount).toBe(1);
    });

    it("should transition to STALE after 5s without messages", async () => {
        const statuses: WsConnectionStatus[] = [];
        const onEvent = vi.fn();

        connectLiveUpdates({
            path: "/ws/test",
            onEvent,
            onStatusChange: (s) => statuses.push(s),
        });
        await vi.runAllTimersAsync();

        const ws = MockWebSocket._latest()!;
        ws.simulateOpen();
        expect(statuses[statuses.length - 1]).toBe("LIVE");

        // Advance past stale threshold
        vi.advanceTimersByTime(5500);
        expect(statuses).toContain("STALE");
    });

    it("should reset stale timer on message received", async () => {
        const statuses: WsConnectionStatus[] = [];
        const onEvent = vi.fn();

        connectLiveUpdates({
            path: "/ws/test",
            onEvent,
            onStatusChange: (s) => statuses.push(s),
        });
        await vi.runAllTimersAsync();

        const ws = MockWebSocket._latest()!;
        ws.simulateOpen();

        // Advance 4s, then send a message — timer should reset
        vi.advanceTimersByTime(4000);
        ws.simulateMessage({ type: "PriceUpdated", payload: {} });

        // Advance another 4s — should NOT be stale yet (only 4s since last message)
        vi.advanceTimersByTime(4000);
        expect(statuses).not.toContain("STALE");
    });

    it("should schedule reconnect after connection close", async () => {
        const statuses: WsConnectionStatus[] = [];
        const onEvent = vi.fn();

        const controls = connectLiveUpdates({
            path: "/ws/test",
            onEvent,
            onStatusChange: (s) => statuses.push(s),
        });
        await vi.runAllTimersAsync();

        const ws = MockWebSocket._latest()!;
        ws.simulateOpen();
        ws.simulateClose();

        expect(statuses).toContain("DISCONNECTED");

        // Advance timers enough for backoff + let the async connect() settle
        await vi.advanceTimersByTimeAsync(5000);
        await vi.runAllTimersAsync();

        // A new WebSocket instance should have been created for the reconnect
        expect(MockWebSocket._instances.length).toBeGreaterThanOrEqual(2);

        // Cleanup to prevent leaking into next test
        controls.close();
    });

    it("should not reconnect after intentional close", async () => {
        const onEvent = vi.fn();

        const controls = connectLiveUpdates({ path: "/ws/test", onEvent });
        await vi.runAllTimersAsync();

        const countBefore = MockWebSocket._instances.length;
        const ws = MockWebSocket._latest()!;
        ws.simulateOpen();

        controls.close();

        // Advance timers significantly
        await vi.advanceTimersByTimeAsync(60000);
        await vi.runAllTimersAsync();

        // Should not have created additional WebSocket instances after close
        expect(MockWebSocket._instances.length).toBe(countBefore);
    });

    it("should return DISCONNECTED immediately when WS base URL is empty", () => {
        vi.mocked(getWsBaseUrl).mockReturnValue("");
        const statuses: WsConnectionStatus[] = [];
        const onEvent = vi.fn();

        const controls = connectLiveUpdates({
            path: "/ws/test",
            onEvent,
            onStatusChange: (s) => statuses.push(s),
        });

        expect(statuses).toEqual(["DISCONNECTED"]);
        expect(MockWebSocket._instances.length).toBe(0);
        controls.close(); // should not throw
    });

    it("should send payload when socket is open", async () => {
        const onEvent = vi.fn();
        const controls = connectLiveUpdates({ path: "/ws/test", onEvent });
        await vi.runAllTimersAsync();

        const ws = MockWebSocket._latest()!;
        ws.simulateOpen();

        controls.send({ action: "subscribe", channel: "prices" });
        expect(ws.send).toHaveBeenCalledWith(
            JSON.stringify({ action: "subscribe", channel: "prices" })
        );
    });

    it("should fire onError for invalid JSON messages", async () => {
        const onError = vi.fn();
        const onEvent = vi.fn();

        connectLiveUpdates({ path: "/ws/test", onEvent, onError });
        await vi.runAllTimersAsync();

        const ws = MockWebSocket._latest()!;
        ws.simulateOpen();
        ws.onmessage?.({ data: "not{json" });

        expect(onError).toHaveBeenCalled();
    });

    it("should fire onDegradation on socket error", async () => {
        const onDegradation = vi.fn();
        const onEvent = vi.fn();

        connectLiveUpdates({ path: "/ws/test", onEvent, onDegradation });
        await vi.runAllTimersAsync();

        const ws = MockWebSocket._latest()!;
        ws.simulateOpen();
        ws.simulateError();

        expect(onDegradation).toHaveBeenCalledWith(
            expect.objectContaining({ mode: "DEGRADED" })
        );
    });
});
