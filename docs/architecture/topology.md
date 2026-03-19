# Topology

**Status:** Canonical topology summary

## Runtime topology

```text
providers
  -> ingest
  -> Redis fanout and durability
  -> engine and governance consumers
  -> API and dashboard consumers
  -> EA bridge and broker execution path
```

## Topology rules

- producer and consumer roles are deployed explicitly
- read-only interfaces stay read-only
- execution paths remain isolated from discretionary UI behavior
- stale recovery paths must be visible so operators know whether the system is live, degraded, or merely preserved

## Why this matters

Most serious failures in automated trading come from topology confusion, not only from strategy quality. Clear topology prevents dashboard bypasses, feed illusions, and accidental engine-only deployments.
