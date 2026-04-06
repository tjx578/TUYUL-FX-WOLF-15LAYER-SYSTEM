# Wolf 30-Point — Implementation Governance

> **Status**: Active governance document.
> **Scope**: All changes to Wolf 30-Point scoring, sub-thresholds, and constitutional gates.

## 1. Purpose

This document defines the governance rules for implementing changes to the
Wolf 30-Point scoring system across Phases A→E. It ensures:

- Authority boundaries remain intact
- Changes are additive-first, breaking-never
- Production runtime is not disrupted
- All changes are auditable

---

## 2. Core Principles

### 2.1 Additive First

All new fields, config keys, and payload entries are **additive**.
No existing field is removed, renamed, or semantically changed.

### 2.2 Default-Safe

Every new config key has a default value that preserves current behavior:

- `fundamental_min: 5` — below current typical F-scores (no new blocks)
- `fta_conflict_veto.enabled: false` — advisory only until explicitly activated
- `fta_conflict_veto.hard_fail_on_conflict: false` — soft mode default

### 2.3 Feature-Flagged

New enforcement behavior is gated behind config flags:

- `fta_conflict_veto.enabled` controls whether L4 constitutional checks FTA conflict
- `fta_conflict_veto.mode` controls ADVISORY vs HARD behavior
- Profile activation controls curriculum vs pragmatic thresholds

### 2.4 Pipeline-Transparent

New payload fields do not alter pipeline flow unless enforcement is explicitly enabled.
Downstream consumers that don't read new fields see no change.

---

## 3. Phase Ordering (Strict)

```
Phase A → Phase B → Phase C → Phase D → Phase E
```

**Do not reorder**. Each phase depends on the previous:

| Phase | Dependency | Produces |
|---|---|---|
| A | None | Divergence map, governance docs |
| B | A | Config keys, additive payload fields |
| C | B | Enforcement logic reading B's config |
| D | C | Profile YAMLs using B+C infrastructure |
| E | D | Telemetry + adapter consuming full stack |

---

## 4. Authority Boundary Rules

### 4.1 L4 Scoring (analysis zone)

- MAY add new fields to `wolf_30_point` payload
- MAY add new classification functions
- MUST NOT emit direction, verdict, or execution signals
- MUST NOT read account state

### 4.2 L4 Constitutional (analysis zone)

- MAY add new sub-gate checks
- MAY add new BlockerCode enum values
- MUST NOT emit verdict or execution signals
- MUST read enforcement config from constitution.yaml

### 4.3 Constitution YAML

- MAY add new sections and keys
- MUST NOT remove or rename existing keys
- New keys MUST have safe defaults documented

### 4.4 ConfigProfileEngine

- MAY autoload from `config/profiles/` directory
- MAY add env-var bootstrap
- MUST NOT bypass constitution.yaml as source of truth
- Profiles override config values, not constitutional structure

### 4.5 Verdict Engine (Layer 12)

- MAY add telemetry fields to return dict
- MUST NOT change verdict logic based on new fields
- `constitution_profile` is metadata, not decision input

---

## 5. Testing Requirements

Each phase must include or maintain:

| Phase | Test Requirement |
|---|---|
| B | Config key presence assertions |
| C | Enforcement unit tests (fundamental_min fail, fta_conflict advisory/hard) |
| D | Profile loading + effective config merge tests |
| E | Verdict payload field assertions |

---

## 6. Rollback Strategy

All changes are designed for safe rollback:

- **Config rollback**: Remove new keys → defaults restore old behavior
- **Code rollback**: New functions are additive; removing them restores old payload
- **Profile rollback**: Delete profile YAML → ConfigProfileEngine falls back to builtin
- **Enforcement rollback**: Set `fta_conflict_veto.enabled: false` → advisory only

---

## 7. Change Log

| Date | Phase | Change | Author |
|---|---|---|---|
| 2026-04 | A | Initial governance document created | System |
