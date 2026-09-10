# Reviewed local source recovery — 2026-09-09

This package preserves selected work discovered in local WOLF15 branches, worktrees and loose source folders. It is based on main `68ad0794e087177571972a7b95f4b7dde70b5286`.

**DO NOT MERGE HISTORICAL PAYLOADS OVER MAIN.** Payloads are inert `.txt` files, not build inputs. Several older auth/viewer implementations weaken current restrictions, and older ingest code lacks current provenance checks. Historical README claims of LIVE readiness are not current evidence. This package grants no deployment, migration, DEMO/LIVE or broker authority.

`manifest.json` records the original relative path, provenance and SHA-256 of every selected or excluded record. Identical bytes share one payload. To recover a selected file, copy its payload to a new, empty review directory using the recorded original path, then verify SHA-256. Never restore automatically into a working repository. Portable harness records additionally specify their reconstruction path and any explicit extraction transformation.

Existing published equivalents were not uploaded again. Transient history is explicitly distinguished from unique final branch trees. The full Git history, original indexes, patches, private configuration and runtime evidence are retained in a separate private local recovery package. This public package is not a complete backup and does not make every original folder safe to delete.

Selection used source provenance review and a bounded local secret/operational-metadata scan. Flagged content was held privately. This is not a full security certification. The portable harness candidate passed 106 isolated tests; that result does not validate historical app payloads or production readiness.

Active observer persistence repair is handled separately as actual source integration; this archive must not be substituted for that tested change.
