# Config Resolver

**Status:** Proposed canonical contract for config authority.

## Why this file exists

The system needs a single explanation of how configuration becomes effective runtime truth. Without that, strategy settings, risk limits, dashboard toggles, and deployment overrides can diverge and create audit gaps.

## Resolver responsibilities

A config resolver should:

- collect configuration from approved sources only
- apply deterministic precedence rules
- expose the effective resolved config to services
- record provenance for auditability
- reject unsafe or partial overrides that violate locked policy

## Recommended precedence

```text
constitutional lock layer
  -> approved environment and deployment overrides
  -> repository defaults
  -> per-service local defaults
```

## Guardrails

- Runtime code must read effective config through one resolver path.
- Ad hoc environment reads inside business logic should be treated as debt.
- Risk limits, execution rules, and lock states must have provenance metadata.
- The dashboard may display config state, but it must not become the authority source.

## Cross-reference

This file complements `config-governance.md` and `lock-enforcement.md`.
