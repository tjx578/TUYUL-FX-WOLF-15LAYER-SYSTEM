# Risk Monitor

**Status:** Canonical monitoring intent

## Purpose

The risk monitor is the operator-facing and machine-readable surface that explains whether the system is inside safe bounds.

## It should track

- feed freshness and producer health
- warmup completeness
- drawdown and exposure state
- lock and governance violations
- open execution risks and pending-order state
- news and macro suppression windows

## Design rule

A risk monitor must explain *why* the system is degraded, not merely report a red status.

## Consumer rule

The dashboard may visualize risk state, but source computation belongs in backend services and governance components.
