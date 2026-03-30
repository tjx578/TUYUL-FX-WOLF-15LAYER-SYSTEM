# Architecture

`architecture/` is the constitutional documentation surface for the TUYUL FX trading operating system.

## What belongs here

Only material that should be treated as production truth:

- system data flow
- end-to-end execution boundaries
- governance and config authority
- risk architecture
- infrastructure and deployment topology
- operational contracts that bind services together

## What does not belong here

- discretionary trading theory
- unvalidated research
- UI brainstorms without backend authority
- historical implementation notes that are no longer normative

## Canonical reading order

1. `data-flow.md`
2. `system-overview.md`
3. `dashboard-control-surface.md`
4. `runtime-topology-current.md`
5. `engine-lineage-zones.md`
6. `config-resolver.md`
7. `lock-enforcement.md`
8. `config-governance.md`
9. `risk-stack.md`
10. `risk-monitor.md`
11. `deployment-railway.md`
12. `topology.md`

## Existing detailed references

This folder also preserves deeper implementation references already present in the repo, including:

- `data-flow-final.md`
- `core/engine-dag-architecture.md`
- `risk/risk-management-summary.md`
- `infrastructure/deployment-baseline.md`
- `governance/final-system-review.md`

Those files remain useful, but the top-level files listed above now define the primary navigation model.
