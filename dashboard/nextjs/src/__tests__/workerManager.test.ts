/**
 * TUYUL FX Wolf-15 — Worker Manager Tests
 *
 * Tests the createWorkerManager wrapper including SSR safety, timeout, and
 * basic message routing. Uses a mock Worker in jsdom.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createWorkerManager } from "@/lib/workers/workerManager";

// Mock Worker class for jsdom environment
class MockWorker {
    onmessage: ((e: MessageEvent) => void) | null = null;
    onerror: ((e: ErrorEvent) => void) | null = null;
    private terminated = false;

    postMessage(data: unknown) {
        if (this.terminated) return;
        // Simulate async response
        setTimeout(() => {
            if (this.onmessage && !this.terminated) {
                const response = { ...(data as Record<string, unknown>), result: "ok" };
                this.onmessage(new MessageEvent("message", { data: response }));
            }
        }, 5);
    }

    terminate() {
        this.terminated = true;
    }
}

describe("createWorkerManager", () => {
    beforeEach(() => {
        vi.useFakeTimers({ shouldAdvanceTime: true });
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it("routes request and returns matching response", async () => {
        const mgr = createWorkerManager<
            { id: string; type: string },
            { id: string; type: string; result: string }
        >(() => new MockWorker() as unknown as Worker);

        const resp = await mgr.request({ id: "test-1", type: "compute" });
        expect(resp.id).toBe("test-1");
        expect(resp.result).toBe("ok");

        mgr.terminate();
    });

    it("rejects with error response type", async () => {
        const errorWorker = new MockWorker();
        // Override postMessage to send error
        errorWorker.postMessage = function (data: unknown) {
            setTimeout(() => {
                if (this.onmessage) {
                    this.onmessage(
                        new MessageEvent("message", {
                            data: { id: (data as Record<string, string>).id, type: "error", error: "test failure" },
                        })
                    );
                }
            }, 5);
        };

        const mgr = createWorkerManager<
            { id: string; type: string },
            { id: string; type: string }
        >(() => errorWorker as unknown as Worker);

        await expect(
            mgr.request({ id: "err-1", type: "compute" })
        ).rejects.toThrow("test failure");

        mgr.terminate();
    });

    it("rejects all pending on terminate", async () => {
        // Worker that never responds
        const silentWorker = new MockWorker();
        silentWorker.postMessage = () => { }; // no-op

        const mgr = createWorkerManager<
            { id: string; type: string },
            { id: string; type: string }
        >(() => silentWorker as unknown as Worker);

        const promise = mgr.request({ id: "pend-1", type: "x" }, 60_000);
        mgr.terminate();

        await expect(promise).rejects.toThrow("Worker terminated");
        expect(mgr.alive).toBe(false);
    });

    it("rejects on timeout", async () => {
        // Worker that never responds
        const silentWorker = new MockWorker();
        silentWorker.postMessage = () => { };

        const mgr = createWorkerManager<
            { id: string; type: string },
            { id: string; type: string }
        >(() => silentWorker as unknown as Worker);

        const promise = mgr.request({ id: "timeout-1", type: "x" }, 100);
        vi.advanceTimersByTime(150);

        await expect(promise).rejects.toThrow("timed out");
        mgr.terminate();
    });

    it("rejects in SSR (no window)", async () => {
        const originalWindow = globalThis.window;
        // Temporarily remove window to simulate SSR
        const globalForSsr = globalThis as { window?: Window & typeof globalThis };
        globalForSsr.window = undefined;

        const mgr = createWorkerManager<
            { id: string; type: string },
            { id: string; type: string }
        >(() => new MockWorker() as unknown as Worker);

        await expect(
            mgr.request({ id: "ssr-1", type: "x" })
        ).rejects.toThrow("Workers unavailable in SSR");

        expect(mgr.alive).toBe(false);

        // Restore window
        globalForSsr.window = originalWindow;
    });
});
