# Docs Taxonomy

This repository now treats documentation as a governed knowledge system, not a flat note dump.

## Canonical structure

```text
docs/
  architecture/   # production truth, governance law, deployable system design
  knowledge/      # human reference, learning material, market/platform knowledge
  concepts/       # experimental ideas, R&D, drafts, future-state thinking
  legacy/         # quarantined historical material, migration references, old summaries
```

## Hard rules

1. `architecture/` is law for system behavior and operational boundaries.
2. `knowledge/` helps humans reason, but must not be treated as executable logic.
3. `concepts/` may influence future design, but is not production truth until promoted.
4. `legacy/` is quarantine; it is preserved for audit and migration only.

## Migration intent

The goal is to keep strong material that already exists, while adding a cleaner front-door so developers, operators, and auditors do not mix system law with research notes or old implementation summaries.

## Entry points

- Start with `docs/architecture/README.md` for production truth.
- Use `docs/knowledge/README.md` for human learning references.
- Use `docs/concepts/README.md` for R&D and idea incubation.
- Use `docs/legacy/README.md` for quarantined historical material.
