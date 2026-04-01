/**
 * Next.js Instrumentation — runs once when the server starts.
 *
 * Patches the global `performance` object to ensure all Web Performance API
 * methods exist. Next.js 15.5+ internal modules (minified as `mgt.*`) call
 * `performance.clearMarks()` and `performance.clearMeasures()` which may be
 * absent or incomplete in stripped-down Node.js Alpine containers.
 */
export async function register() {
  if (typeof globalThis.performance !== "undefined") {
    const perf = globalThis.performance;

    // Ensure clearMarks exists (required by Next.js internal perf tracking)
    if (typeof perf.clearMarks !== "function") {
      perf.clearMarks = (_name?: string) => {
        /* no-op polyfill */
      };
    }

    // Ensure clearMeasures exists (same internal usage pattern)
    if (typeof perf.clearMeasures !== "function") {
      perf.clearMeasures = (_name?: string) => {
        /* no-op polyfill */
      };
    }
  } else {
    // If performance is completely absent, provide a minimal stub.
    // This should not happen on Node.js 16+ but guards edge cases.
    (globalThis as Record<string, unknown>).performance = {
      now: () => Date.now(),
      mark: () => {},
      measure: () => {},
      clearMarks: () => {},
      clearMeasures: () => {},
      getEntriesByType: () => [],
      getEntriesByName: () => [],
    };
  }
}
