# Explicit attested-image mode for T14

The normal opt-in T14 test continues to build the repository Dockerfile. A
separate explicit mode accepts an immutable image prepared by a reviewed local
runtime-source replacement procedure. The mode is selected only when both
`WOLF15_T14_PREBUILT_IMAGE_ID` and `WOLF15_T14_IMAGE_ATTESTATION` are provided.
Expected final source commit/tree, disposable database/Redis images and the
existing smoke enable flag remain mandatory. Partial inputs and mutable tags
are rejected.

The supplied `wolf15.runtime-source-image/v1` attestation binds the final Git
commit/tree, immutable image ID, original retained base identity and rootfs
diff IDs, base export hash, archive hash, actual production projection hash,
runtime configuration hash and declared build mode. The original normal-build
failure remains separate evidence. An attested-image run records explicitly
that it did not rebuild the normal Dockerfile.

Before fixtures start, T14 inspects the image and validates its exact source
labels, platform, runtime config and base layer prefix. A network-none,
read-only helper using the image's default user rehashes every actual `/app`
file, directory and symlink. It checks the separate projected inventory in
`/usr/share/wolf15-build/projection.json` and UID/GID1000. The helper code is
supplied directly by the test harness, not loaded from the image. The complete
Git archive and filtered production projection retain different identities
and counts.

The API and orchestrator use the same immutable image ID. Their existing
entrypoint, process ownership, API-only, health/readiness, execution-OFF and
SHUTDOWN assertions remain. Supplied prebuilt images are retained; disposable
containers and networks still belong to the T14 campaign. In this mode Redis,
PostgreSQL, API and orchestrator have memory limits128/256/512/512MiB, no extra
swap and one CPU each. The filesystem helper is limited to128MiB. Exceeding a
limit is a failure, not authority to increase it automatically.

This is an image/runtime acceptance path. It does not prove normal-Dockerfile
dependency resolution, production R01-R08, Redis server-loss recovery, legacy
state migration, installed EA/EX5 compatibility, or broker effects. No execution
authority is granted by the attestation or a successful T14 result.
