# Existing Channel B measurement contract

The repository already has scripts/reconcile_channel_b.py -> ops.mt5_mcp.reconcile.main -> run_reconciliation, using Native MT5 MCP plus six approved wolf15_audit views. Reuse this collector/reconciler; the earlier statement that an independent-reader interface needed to be created from scratch was too broad. Active binding and acceptance remain absent.

Concrete repair: measured broker payloads require matching integer counts, records list of mappings, coherent MEASURED/MEASURED_EMPTY state, non-truncation and valid unique positive integer tickets within each non-account payload. Measurement flags require explicit booleans. Missing, string, float or boolean changed_tuples cannot establish zero mutation. The emitted payload_consistent field explains rejection without raw ticket disclosure.

Expected versus actual: 19 new malformed/ambiguous evidence cases do not pass the gate. Existing measured empty, matched and mismatched cases retain their outcomes. Final br2: 49 passed, no skip, exact collection/JUnit identities. Initial br1 had one CLI fixture failure because sanitized test environment lacks a home directory; fixture Path.home now uses tmp_path, with production behavior unchanged. Source server emits integer ticket/count values; no collector protocol replacement.

Review: checks are linear in bounded records with per-payload ticket-set storage. Account binding and existing non-readiness fields are retained. This validates consistency, not attestation authenticity, broker connectivity, live reconciliation or strategy-risk-execution acceptance. Independent agent review unavailable. No production, broker, README or canonical-register mutation. Milestones remain 0/6.

Next executable source work: bind report provenance (collector/source/window/account and immutable evidence digest) to existing Channel B output and define its consumer acceptance; do not promote executor heartbeat broker_ledger_reconciled into independent truth.
