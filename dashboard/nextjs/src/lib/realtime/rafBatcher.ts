/**
 * TUYUL FX Wolf-15 — RAF Message Batcher
 *
 * Optional requestAnimationFrame batching layer for ultra-high symbol count
 * scenarios (50+ symbols ticking simultaneously). Sits between the WebSocket
 * onMessage handler and store dispatches.
 *
 * When enabled, incoming events are queued and flushed once per animation
 * frame (~16ms at 60fps), collapsing duplicate keys (e.g. same symbol
 * price updates) so only the latest value per key reaches the consumer.
 *
 * Usage:
 *   const batcher = createRafBatcher<PriceData>({
 *     keyFn: (event) => event.symbol,
 *     onFlush: (batch) => setPriceMap((prev) => mergeMap(prev, batch)),
 *   });
 *   // In WS onMessage:
 *   batcher.push(symbol, priceData);
 *   // On cleanup:
 *   batcher.dispose();
 *
 * When RAF batching is not needed, pass events directly to stores as before.
 */

export interface RafBatcherOptions<T> {
    /** Called once per frame with the collapsed batch (key → latest value). */
    onFlush: (batch: Record<string, T>) => void;
    /** Maximum events to buffer before forcing an immediate flush (backpressure). */
    maxBufferSize?: number;
}

export interface RafBatcher<T> {
    /** Queue an event. Duplicate keys within the same frame are collapsed (last-write-wins). */
    push: (key: string, value: T) => void;
    /** Flush any pending events immediately (e.g. on unmount). */
    flush: () => void;
    /** Dispose: cancel pending RAF and flush remaining. */
    dispose: () => void;
    /** Current pending count (for diagnostics). */
    readonly pending: number;
}

const DEFAULT_MAX_BUFFER = 500;

export function createRafBatcher<T>(options: RafBatcherOptions<T>): RafBatcher<T> {
    const { onFlush, maxBufferSize = DEFAULT_MAX_BUFFER } = options;

    let buffer: Record<string, T> = {};
    let count = 0;
    let rafId: number | null = null;
    let disposed = false;

    function scheduleFlush() {
        if (rafId !== null || disposed) return;
        rafId = requestAnimationFrame(() => {
            rafId = null;
            doFlush();
        });
    }

    function doFlush() {
        if (count === 0) return;
        const batch = buffer;
        buffer = {};
        count = 0;
        onFlush(batch);
    }

    function push(key: string, value: T) {
        if (disposed) return;
        if (!(key in buffer)) count++;
        buffer[key] = value;

        // Backpressure: flush immediately if buffer is too large
        if (count >= maxBufferSize) {
            if (rafId !== null) {
                cancelAnimationFrame(rafId);
                rafId = null;
            }
            doFlush();
        } else {
            scheduleFlush();
        }
    }

    function flush() {
        if (rafId !== null) {
            cancelAnimationFrame(rafId);
            rafId = null;
        }
        doFlush();
    }

    function dispose() {
        disposed = true;
        flush();
    }

    return {
        push,
        flush,
        dispose,
        get pending() {
            return count;
        },
    };
}
