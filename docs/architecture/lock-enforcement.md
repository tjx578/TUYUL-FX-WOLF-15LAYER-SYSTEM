# Lock Enforcement

**Status:** Canonical governance rule

## Principle

A trading system cannot be fund-grade if production rules can be casually bypassed. Lock enforcement is the layer that prevents unsafe mutation of protected settings and mode transitions.

## What must be lockable

- constitutional thresholds
- risk ceilings and drawdown protections
- execution mode restrictions
- provider failover policy
- deployment mode changes that alter authority boundaries

## Enforcement expectations

- locked fields reject mutation unless an explicit approval path is satisfied
- attempted violations are logged with actor, timestamp, and requested delta
- services consume the same lock state; no side-channel override is allowed
- lock violations downgrade the system to a safe operational posture when needed

## Operational outcome

Lock enforcement is not a UI feature. It is a backend control plane behavior that all interfaces must respect.
