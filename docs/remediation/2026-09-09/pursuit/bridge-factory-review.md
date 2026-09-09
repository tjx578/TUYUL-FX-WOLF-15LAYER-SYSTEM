# Executor bridge factory binding

create_app now accepts the explicit boolean executor_bridge_enabled=False. Default applications retain no bridge routes. True mounts the existing authenticated router; ambiguous values are rejected. Registry boot errors and path collisions raise even when bootstrap fail-open is configured. Command production/delivery/order flags are untouched and no existing entrypoint is activated.

Expected versus actual: default plus an environment-only request remains 404; explicit opt-in routes reject missing credentials with 401, cross-executor access with 403, and missing auth configuration with 503 before repository methods. Valid machine authentication reaches status and returns a fixture response; repository veto remains 409. All mounted bridge route methods reject unauthenticated requests. Duplicate registration and degraded router bootstrap fail construction.

35 final tests pass, including 13 new factory cases, with exact JUnit/collection identity and unchanged source during run. The initial 33-case run exposed a duplicate check gap; the legacy generic guard did not raise on repeated inclusion in this FastAPI environment. An explicit pre-mount path collision check fixes this binding, without claiming the generic guard has been repaired globally.

Tests retain the actual inner factory and middleware but stub unrelated router imports and telemetry. TestClient does not run lifespan. Repositories are mocked; no full-registry acceptance, PostgreSQL, deployment or broker proof. Review was serial. Existing entrypoints still require a separately bound opt-in before runtime use; independent broker attestation remains missing.

No milestone closed; canonical register and README unchanged. Push, merge and runtime gates remain HOLD. Next source work: independent-reader evidence contract and verification boundary, then bound service-entrypoint and full-registry acceptance when the operational package permits it.
