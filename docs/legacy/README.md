# Legacy

`legacy/` is the quarantine zone for historical notes, migration summaries, and old materials that should remain available for audit but should not be mistaken for production truth.

## Rules

- preserve for traceability
- do not treat as canonical design input
- only consult during migration, audit, or archaeology work
- canonical architecture lives in `docs/architecture/`

## Current classes

- implementation summaries
- production-upgrade snapshots
- code citation bundles
- security advisories
- legacy UI concepts

## architecture-history/

Historical architecture documents relocated from the canonical surface:

| File | Origin | Reason |
| ------ | -------- | -------- |
| `docker-compose-legacy.md` | `docs/architecture/infrastructure/` | Superseded by `deployment-railway.md` |
| `final-system-review.md` | `docs/architecture/governance/` | Historical v7.4r∞ snapshot; current rules live in `system-overview.md` |
| `unified-architecture-v2.1.md` | `docs/concepts/architecture-history/` | Historical unified arch; current topology in `runtime-topology-current.md` |

These files are NOT authoritative for current system behavior.
