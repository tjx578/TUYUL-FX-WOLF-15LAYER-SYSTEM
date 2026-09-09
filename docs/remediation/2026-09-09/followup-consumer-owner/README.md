# S03 consumer and shared owner checkpoint

**INCOMPLETE / HOLD**. Source `3d8df68057d6a0c2f9dc1b1969651f8f298aa713`. This package implements consumer/owner/transport source and acceptance fixtures. Actual PostgreSQL, owner handover, HTTPS deployment and runtime policy binding are not proven. No milestone is closed.

## Source behavior

The existing `StrategyShadowEvidenceV2Repository.activity_consumer` binds a typed consumer to that owner's PostgreSQL client and lifecycle repository. Inbox, lifecycle upsert, logical activity mapping, cursor and analysis emission use one transaction. Policy receives freshly locked lifecycle rows, not a retained reducer. Recovery is capped at 1000 rows per symbol and fails explicitly on excess; no benchmark or retention policy is claimed.

`transfer_owner` uses explicit expected-generation CAS under the same symbol lock used by consumer transactions. It never acquires ownership automatically. `bind_owner` checks generation/token and sets the transaction-local token. Migration `20260909_03` applies a trigger to every INSERT/UPDATE/DELETE on the existing lifecycle table. Once a symbol has an owner row, missing/stale tokens reject legacy and new writes. Repository legacy persistence accepts an explicit fence; the legacy worker does not invent one. Unmanaged symbols keep their existing behavior. Runtime DB grants and operational handover remain unbound; this is not protection against a database administrator disabling triggers.

The logical mapping key is consumer_scope_id + activity_id. A policy/scope change cannot evade the old mapping by changing its hash; it requires explicit migration. Duplicate committed delivery is checked before expiry/source reacquisition. Payload conflicts enter a quarantine table without overwriting the inbox. Missing predecessor returns WAITING_PREDECESSOR. Emission identity excludes delivery; unchanged material state preserves the first emission.

`ActivityTransportBinding` requires a fixed HTTPS destination/path, identity, key, and freshness window. Requests authenticate identity, destination, timestamp and exact body with HMAC. `ActivityHTTPSender` verifies TLS, disables redirects/inherited proxies, and returns only the receiver's delivery/hash/outcome tuple. API `create_app(activity_delivery_endpoint=...)` mounts the route only with an explicit endpoint object; invalid/duplicate binding fails rather than falling back to a liveness-only app. Defaults do not activate a consumer. No active endpoint, approved policy, attestor or credentials are supplied by these tests.

## Expected versus actual evidence

| Scenario | Evidence |
|---|---|
| Consumer commit, relay lease expires, old ACK ignored, duplicate replay, successor continues | Local model covers commit/expired ACK/replay; authored PostgreSQL + authenticated ASGI test covers the complete sequence; database NOT_EXECUTED |
| Failure after mapping/emission/inbox/cursor write | Local transactional model PASS; four actual PostgreSQL rollback cases authored, NOT_EXECUTED |
| Payload conflict / missing predecessor | Local model PASS; database quarantine/order cases authored, NOT_EXECUTED |
| Owner handover blocks old consumer and unfenced legacy upsert | Local model validates stale owner; DB trigger and actual legacy-writer negative test authored, NOT_EXECUTED |
| Concurrent duplicates / restart / advisory attachment | Actual PostgreSQL cases authored, NOT_EXECUTED |
| Authenticated request and API factory binding | Local ASGI/model PASS; live HTTPS/TLS endpoint NOT_EXECUTED |
| Changed policy must not create a new mapping for the same logical activity | Local regression PASS |

Latest selected suite: **185 passed, 0 failures, 0 skips**. Exact JUnit identities and working source hashes were verified; Git CRLF-only differences are enumerated in `evidence/source-commit.json`. Actual package versions are recorded in the offline review (FastAPI 0.141.1, Pydantic 2.9.2, HTTPX 0.27.2); requirements contain version ranges, so this is not a fully locked Linux dependency proof. A retained earlier failure was a test's direct route-list assumption under FastAPI's included-router representation; the final test checks the HTTP behavior.

The original **45** and producer **7** tests are byte-unchanged. The separate consumer gate has **11** collected cases. All **63** skipped in the disabled control; the strict consumer gate rejected eleven skips on the source commit. One Alembic head and offline SQL passed; no migration was applied. `acceptance-inventory.json` maps D01-D11 without promoting authored/skipped tests to DONE.

## Remaining acceptance and activation boundary

Run explicit migrations and the three separate gates on a verified disposable PostgreSQL/Linux runner before extending features. Bind the actual owner policy/attestor, least-privilege DB access, authenticated destination and handover configuration; prove the real HTTPS path and lifecycle acceptance. Keep legacy directional consumer migration and DEMO account/risk/EA/canary/independent broker-reader work separate. GitHub required checks and DEMO remain HOLD. No Railway, production database, VPS, broker or billing mutation occurred.
