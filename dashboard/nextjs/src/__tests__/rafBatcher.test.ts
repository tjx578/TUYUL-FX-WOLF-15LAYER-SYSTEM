/**
 * Unit tests for lib/realtime/rafBatcher.ts
 *
 * Tests:
 *  - Last-write-wins key collapse within a frame
 *  - Flush triggers once per RAF cycle
 *  - Backpressure: immediate flush when buffer >= maxBufferSize
 *  - dispose() flushes remaining and prevents further pushes
 *  - pending count accuracy
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createRafBatcher } from "@/lib/realtime/rafBatcher";

// ── Mock requestAnimationFrame / cancelAnimationFrame ────────

let rafCallbacks: Array<{ id: number; cb: FrameRequestCallback }> = [];
let rafIdCounter = 0;

beforeEach(() => {
    rafCallbacks = [];
    rafIdCounter = 0;

    globalThis.requestAnimationFrame = vi.fn((cb: FrameRequestCallback) => {
        const id = ++rafIdCounter;
        rafCallbacks.push({ id, cb });
        return id;
    });

    globalThis.cancelAnimationFrame = vi.fn((id: number) => {
        rafCallbacks = rafCallbacks.filter((r) => r.id !== id);
    });
});

afterEach(() => {
    vi.restoreAllMocks();
});

function flushRaf() {
    const pending = [...rafCallbacks];
    rafCallbacks = [];
    for (const { cb } of pending) {
        cb(performance.now());
    }
}

// ── Tests ────────────────────────────────────────────────────

describe("createRafBatcher", () => {
    it("should collapse duplicate keys within a frame (last-write-wins)", () => {
        const onFlush = vi.fn();
        const batcher = createRafBatcher<number>({ onFlush });

        batcher.push("EURUSD", 1.10);
        batcher.push("EURUSD", 1.11);
        batcher.push("EURUSD", 1.12);

        flushRaf();

        expect(onFlush).toHaveBeenCalledOnce();
        expect(onFlush).toHaveBeenCalledWith({ EURUSD: 1.12 });
    });

    it("should batch multiple keys and flush together", () => {
        const onFlush = vi.fn();
        const batcher = createRafBatcher<number>({ onFlush });

        batcher.push("EURUSD", 1.10);
        batcher.push("GBPUSD", 1.30);
        batcher.push("USDJPY", 150.5);

        flushRaf();

        expect(onFlush).toHaveBeenCalledWith({
            EURUSD: 1.10,
            GBPUSD: 1.30,
            USDJPY: 150.5,
        });
    });

    it("should not flush when buffer is empty", () => {
        const onFlush = vi.fn();
        createRafBatcher<number>({ onFlush });

        flushRaf();

        expect(onFlush).not.toHaveBeenCalled();
    });

    it("should track pending count accurately", () => {
        const onFlush = vi.fn();
        const batcher = createRafBatcher<number>({ onFlush });

        expect(batcher.pending).toBe(0);

        batcher.push("EURUSD", 1.10);
        expect(batcher.pending).toBe(1);

        batcher.push("GBPUSD", 1.30);
        expect(batcher.pending).toBe(2);

        // Duplicate key should not increase count
        batcher.push("EURUSD", 1.11);
        expect(batcher.pending).toBe(2);

        flushRaf();
        expect(batcher.pending).toBe(0);
    });

    it("should flush immediately on backpressure (buffer >= maxBufferSize)", () => {
        const onFlush = vi.fn();
        const batcher = createRafBatcher<number>({ onFlush, maxBufferSize: 3 });

        batcher.push("A", 1);
        batcher.push("B", 2);
        // This should trigger immediate flush (3 >= 3)
        batcher.push("C", 3);

        // onFlush called without waiting for RAF
        expect(onFlush).toHaveBeenCalledWith({ A: 1, B: 2, C: 3 });
        expect(batcher.pending).toBe(0);
    });

    it("should flush() manually when called", () => {
        const onFlush = vi.fn();
        const batcher = createRafBatcher<number>({ onFlush });

        batcher.push("EURUSD", 1.10);
        batcher.flush();

        expect(onFlush).toHaveBeenCalledWith({ EURUSD: 1.10 });
        expect(batcher.pending).toBe(0);
    });

    it("should flush remaining and stop accepting pushes after dispose()", () => {
        const onFlush = vi.fn();
        const batcher = createRafBatcher<number>({ onFlush });

        batcher.push("EURUSD", 1.10);
        batcher.dispose();

        // Should have flushed remaining
        expect(onFlush).toHaveBeenCalledWith({ EURUSD: 1.10 });

        // Further pushes should be ignored
        batcher.push("GBPUSD", 1.30);
        flushRaf();

        expect(onFlush).toHaveBeenCalledOnce(); // only the dispose flush
    });

    it("should not schedule multiple RAF callbacks for consecutive pushes", () => {
        const onFlush = vi.fn();
        const batcher = createRafBatcher<number>({ onFlush });

        batcher.push("A", 1);
        batcher.push("B", 2);
        batcher.push("C", 3);

        // Only one RAF should be scheduled
        expect(rafCallbacks).toHaveLength(1);
    });
});
