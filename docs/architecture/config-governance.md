# Config Governance

**Status:** Canonical governance workflow

## Objective

Config governance defines how a proposed change becomes an approved and auditable production change instead of an undocumented tweak.

## Workflow

```text
change proposal
  -> validation against schema and lock policy
  -> approval workflow
  -> effective config publication
  -> runtime acknowledgement
  -> audit log and rollback plan
```

## Minimum governance requirements

- every config change has an origin and reason
- high-risk fields require explicit approval, not silent overwrite
- publication is atomic so services do not consume mixed config states
- the system can answer who changed what, when, and under which approval

## Separation of concerns

- `config-resolver.md` explains how effective config is read
- `lock-enforcement.md` explains what cannot change freely
- this file explains the lifecycle of change approval and publication
