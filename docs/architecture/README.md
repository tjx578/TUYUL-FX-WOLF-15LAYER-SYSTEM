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

1. `reference-architecture.md` — constitutional worldview & zone model (v3.0)
2. `data-flow.md`
3. `system-overview.md`
4. `dashboard-control-surface.md`
5. `runtime-topology-current.md`
6. `component-inventory-current.md`
7. `deployment-classification.md`
8. `realtime-interfaces-current.md`
9. `engine-lineage-zones.md`
10. `config-resolver.md`
11. `lock-enforcement.md`
12. `config-governance.md`
13. `risk-stack.md`
14. `risk-monitor.md`
15. `deployment-railway.md`
16. `topology.md`

## Existing detailed references

This folder also preserves deeper implementation references already present in the repo, including:

- `data-flow-final.md`
- `core/engine-dag-architecture.md`
- `risk/risk-management-summary.md`
- `infrastructure/deployment-baseline.md`
- `governance/final-system-review.md`

Those files remain useful, but the top-level files listed above now define the primary navigation model.
