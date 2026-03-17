/**
 * TUYUL FX Wolf-15 — Worker Manager
 *
 * Type-safe wrapper around Web Workers with promise-based request/response,
 * automatic lifecycle management, and SSR safety (no-op on server).
 *
 * Usage:
 *   const mgr = createWorkerManager<Req, Resp>(() =>
 *     new Worker(new URL("../workers/candle.worker.ts", import.meta.url))
 *   );
 *   const result = await mgr.request({ type: "aggregate_ticks", ... });
 *   mgr.terminate();
 */

import type { WorkerErrorResponse } from "@/workers/protocol";

type ResponseWithId = { id: string };

export interface WorkerManager<TReq extends { id: string }, TResp extends ResponseWithId> {
    /** Send a request and await the matching response (by id). */
    request: (msg: TReq, timeoutMs?: number) => Promise<TResp>;
    /** Terminate the worker immediately. Rejects all pending requests. */
    terminate: () => void;
    /** Whether the worker is alive. */
    readonly alive: boolean;
}

const DEFAULT_TIMEOUT_MS = 10_000;

/**
 * Create a managed worker instance with promise-based RPC.
 *
 * @param factory — Function that creates the Worker. Called lazily on first request.
 *                  Must use `new Worker(new URL(...))` for Next.js webpack to bundle.
 */
export function createWorkerManager<
    TReq extends { id: string },
    TResp extends ResponseWithId,
>(factory: () => Worker): WorkerManager<TReq, TResp> {
    // SSR guard — Web Workers don't exist on the server
    if (typeof window === "undefined") {
        return {
            request: () => Promise.reject(new Error("Workers unavailable in SSR")),
            terminate: () => { },
            get alive() { return false; },
        };
    }

    let worker: Worker | null = null;
    let alive = true;
    const pending = new Map<string, {
        resolve: (value: TResp) => void;
        reject: (reason: Error) => void;
        timer: ReturnType<typeof setTimeout>;
    }>();

    function getWorker(): Worker {
        if (!worker) {
            worker = factory();
            worker.onmessage = (e: MessageEvent<TResp | WorkerErrorResponse>) => {
                const data = e.data as Record<string, unknown>;
                const id = data.id as string;
                const entry = pending.get(id);
                if (!entry) return; // orphaned response — ignore
                pending.delete(id);
                clearTimeout(entry.timer);

                if (data.type === "error") {
                    entry.reject(new Error((data as unknown as WorkerErrorResponse).error));
                } else {
                    entry.resolve(e.data as TResp);
                }
            };
            worker.onerror = (ev) => {
                // Reject all pending on unrecoverable worker error
                const err = new Error(ev.message || "Worker error");
                for (const [, entry] of pending) {
                    clearTimeout(entry.timer);
                    entry.reject(err);
                }
                pending.clear();
            };
        }
        return worker;
    }

    function request(msg: TReq, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<TResp> {
        if (!alive) return Promise.reject(new Error("Worker terminated"));
        return new Promise<TResp>((resolve, reject) => {
            const timer = setTimeout(() => {
                pending.delete(msg.id);
                reject(new Error(`Worker request ${msg.id} timed out after ${timeoutMs}ms`));
            }, timeoutMs);

            pending.set(msg.id, { resolve, reject, timer });
            getWorker().postMessage(msg);
        });
    }

    function terminate() {
        alive = false;
        if (worker) {
            worker.terminate();
            worker = null;
        }
        const err = new Error("Worker terminated");
        for (const [, entry] of pending) {
            clearTimeout(entry.timer);
            entry.reject(err);
        }
        pending.clear();
    }

    return {
        request,
        terminate,
        get alive() { return alive; },
    };
}
