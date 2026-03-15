/**
 * Snapshot + Stream Merge Utilities
 *
 * Formal contract for merging a REST snapshot bootstrap with live WS deltas.
 *
 * Rules:
 *   1. Snapshot always renders first — user sees data immediately from REST.
 *   2. WS deltas override snapshot state for matching keys.
 *   3. Stale WS deltas (older timestamp than snapshot) are discarded.
 *   4. Page keeps rendering during reconnect in degraded mode (snapshot persists).
 */

/**
 * Merge a WS delta into an existing map (e.g. prices, trades by ID).
 * Delta keys override snapshot keys; snapshot keys with no delta are kept.
 */
export function mergeMap<T extends Record<string, unknown>>(
  snapshot: T,
  delta: Partial<T>
): T {
  return { ...snapshot, ...delta };
}

/**
 * Merge a single record delta into a snapshot, guarded by timestamp.
 * If delta.timestamp <= snapshot.timestamp, the delta is discarded (stale guard).
 */
export function mergeSingle<T extends { timestamp?: string | number }>(
  snapshot: T | null,
  delta: T
): T {
  if (!snapshot) return delta;
  const snapshotTs = snapshot.timestamp ?? 0;
  const deltaTs = delta.timestamp ?? 0;
  const snapshotTime = typeof snapshotTs === "string" ? Date.parse(snapshotTs) : snapshotTs;
  const deltaTime = typeof deltaTs === "string" ? Date.parse(deltaTs) : deltaTs;
  if (deltaTime < snapshotTime) return snapshot; // stale delta — discard
  return delta;
}

/**
 * Apply a delta to a list (upsert by ID field).
 * Items missing from delta keep their snapshot state.
 */
export function mergeList<T extends { id?: string }>(
  snapshot: T[],
  delta: T
): T[] {
  if (!delta.id) return [...snapshot, delta];
  const idx = snapshot.findIndex((item) => item.id === delta.id);
  if (idx === -1) return [...snapshot, delta];
  const next = [...snapshot];
  next[idx] = delta;
  return next;
}
