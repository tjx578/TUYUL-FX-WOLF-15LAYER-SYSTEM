"""Explicit Linux operator utility; prepare defaults to offline dry validation.

No production target, credential name, risk value or runtime gate has a default.
Windows can dry-validate inputs; protected archive/apply operations fail closed.
"""

from __future__ import annotations

import argparse
import os
import signal
import stat
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from services.orchestrator.legacy_import_contract import (
    MAX_BYTES,
    PROCESS_IDS,
    ImportHoldError,
    OperationDeadlineError,
    digest,
    encoded,
    load_prepared,
    prepare_documents,
    strict_json,
)
from services.orchestrator.legacy_state_import import apply_once, reconcile_observation


def read_input(path: Path) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ImportHoldError("INPUT_TOO_LARGE")
    return raw


@contextmanager
def protected_parent(path: Path):
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise ImportHoldError("PROTECTED_ARCHIVE_REQUIRES_POSIX")
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise ImportHoldError("ABSOLUTE_PROTECTED_PATH_REQUIRED")
    for part in (path.parent, *path.parent.parents):
        if stat.S_ISLNK(part.lstat().st_mode):
            raise ImportHoldError("SYMLINK_PARENT_REJECTED")
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(parent)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ImportHoldError("PARENT_MUST_BE_OWNER_ONLY_0700")
        yield parent
    finally:
        os.close(parent)


def protected_read(path: Path) -> bytes:
    with protected_parent(path) as parent:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
            ):
                raise ImportHoldError("ARCHIVE_MUST_BE_OWNER_ONLY_REGULAR_0600")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ImportHoldError("INPUT_TOO_LARGE")
            return raw
        finally:
            os.close(descriptor)


def protected_write(path: Path, raw: bytes) -> None:
    if len(raw) > MAX_BYTES:
        raise ImportHoldError("OUTPUT_TOO_LARGE")
    with protected_parent(path) as parent:
        descriptor = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(descriptor)
            os.fsync(parent)
        finally:
            os.close(descriptor)
    if protected_read(path) != raw:
        raise ImportHoldError("PROTECTED_PERSISTENCE_VERIFICATION_FAILED")


def verify_evidence(package: dict[str, Any]) -> None:
    for item in package["evidence"].values():
        if digest(read_input(Path(item["locator"]))) != item["sha256"]:
            raise ImportHoldError("PACKAGE_EVIDENCE_HASH_MISMATCH")


def credential_in_memory(package: dict[str, Any], name: str, environment: Any) -> str:
    if not name or any(environment.get(key) != package["process_binding"][key] for key in PROCESS_IDS):
        raise ImportHoldError("PROCESS_BINDING_MISMATCH")
    value = environment.get(name)
    if not isinstance(value, str) or not value:
        raise ImportHoldError("REDIS_CREDENTIAL_NOT_AVAILABLE")
    try:
        url = urlsplit(value)
        endpoint = {
            "scheme": url.scheme,
            "host": url.hostname,
            "port": url.port,
            "database": 0 if url.path in {"", "/"} else int(url.path.removeprefix("/")),
        }
        if endpoint != package["endpoint"] or url.query or url.fragment or not url.password or value != value.strip():
            raise ValueError
    except ValueError as exc:
        raise ImportHoldError("REDIS_ENDPOINT_OR_CREDENTIAL_METADATA_MISMATCH") from exc
    return value


@contextmanager
def operation_deadline(seconds: int):
    if os.name != "posix" or not hasattr(signal, "SIGALRM"):
        raise ImportHoldError("BOUNDED_APPLY_REQUIRES_POSIX")

    def expired(_signum: int, _frame: Any) -> None:
        raise OperationDeadlineError

    previous = signal.signal(signal.SIGALRM, expired)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def connect(package: dict[str, Any], url: str):
    # Import only for explicit apply. Zero retries; a single connection is held.
    import redis
    from redis.backoff import NoBackoff
    from redis.retry import Retry

    client = redis.Redis.from_url(
        url,
        decode_responses=False,
        single_connection_client=True,
        socket_connect_timeout=package["connect_timeout_seconds"],
        socket_timeout=package["read_timeout_seconds"],
        retry=Retry(NoBackoff(), 0),
        retry_on_timeout=False,
        health_check_interval=0,
    )
    try:
        return SingleConnection(client)
    except BaseException:
        client.close()
        raise


class SingleConnection:
    """Disallow Redis's implicit reconnect during a later release/read command.

    Bound to the installed redis-py single-connection API. A failed call disables
    subsequent network calls; close remains a local socket/pool cleanup. Actual
    driver/Redis verification is a separate gate from offline adapter tests.
    """

    def __init__(self, client: Any) -> None:
        self._client = client
        self._connection = client.connection
        self._socket = self._connection._sock if self._connection is not None else None
        if self._socket is None:
            raise ImportHoldError("INITIAL_REDIS_CONNECTION_NOT_ESTABLISHED")
        self._usable = True

    def _call(self, name: str, *args: Any) -> Any:
        if (
            not self._usable
            or self._client.connection is not self._connection
            or self._connection._sock is not self._socket
        ):
            raise ImportHoldError("RECONNECT_FORBIDDEN")
        try:
            return getattr(self._client, name)(*args)
        except BaseException:
            self._usable = False
            raise

    def eval(self, *args: Any) -> Any:
        return self._call("eval", *args)

    def mget(self, keys: list[str]) -> Any:
        return self._call("mget", keys)

    def close(self) -> None:
        self._usable = False
        self._client.close()


def validate_destinations(package: dict[str, Any], *outputs: Path | None) -> Path:
    """Detect aliases before consuming authority; this is not a volume proof."""
    marker = Path(package["operation_marker_path"])
    paths = [marker, *(path for path in outputs if path is not None)]
    normalized = [os.path.normcase(str(path.resolve(strict=False))) for path in paths]
    if len(set(normalized)) != len(normalized):
        raise ImportHoldError("IMPORT_DESTINATION_ALIAS_REJECTED")
    return marker


def execute(args: argparse.Namespace) -> dict[str, Any]:
    now = datetime.now(UTC)
    if args.command == "prepare":
        package, snapshot = strict_json(read_input(args.package)), strict_json(read_input(args.snapshot))
        archive, manifest = prepare_documents(package, snapshot, now=now)
        verify_evidence(package)
        if args.write_archive:
            if args.archive is None or args.manifest is None or args.archive == args.manifest:
                raise ImportHoldError("DISTINCT_EXPLICIT_OUTPUTS_REQUIRED")
            validate_destinations(package, args.archive, args.manifest)
            protected_write(args.archive, archive)
            protected_write(args.manifest, manifest)
        return {
            "status": "PREPARED" if args.write_archive else "DRY_PREPARED_NO_WRITES",
            "archive_sha256": digest(archive),
            "manifest_sha256": digest(manifest),
            "package_claims": "HASH_BOUND_OPERATOR_EVIDENCE_NOT_RUNTIME_OBSERVED",
            "connections": 0,
        }

    manifest, archive = protected_read(args.manifest), protected_read(args.archive)
    if args.command == "reconcile":
        return reconcile_observation(manifest, archive, protected_read(args.state_observation))
    package, _ = load_prepared(manifest, archive, now=now)
    verify_evidence(package)
    marker = validate_destinations(package, args.manifest, args.archive, args.receipt)
    if not args.enable_apply:
        return {"status": "DRY_APPLY_VALIDATED_NO_CONNECTION", "connections": 0}
    if args.receipt is None or not args.credential_env:
        raise ImportHoldError("EXPLICIT_RECEIPT_AND_CREDENTIAL_REFERENCE_REQUIRED")
    if args.receipt.exists():
        raise ImportHoldError("RECEIPT_ALREADY_EXISTS")
    with protected_parent(args.receipt):
        pass
    with protected_parent(marker):
        pass
    url = credential_in_memory(package, args.credential_env, os.environ)
    protected_write(
        marker,
        encoded(
            {
                "status": "ATTEMPT_CONSUMED_BEFORE_CONNECTION",
                "operation_id": package["operation_id"],
                "manifest_sha256": digest(manifest),
            }
        ),
    )
    result: dict[str, Any] = {
        "status": "AMBIGUOUS",
        "reason": "CONNECTION_OR_DEADLINE_FAILURE_NO_RETRY",
        "operation_id": package["operation_id"],
    }
    client = None
    try:
        with operation_deadline(package["total_timeout_seconds"]):
            try:
                client = connect(package, url)
                result = apply_once(client, manifest, archive)
            finally:
                if client is not None:
                    client.close()
    except OperationDeadlineError:
        result["reason"] = "DEADLINE_NO_FURTHER_REDIS_CALLS"
    except Exception:
        # Never serialize backend exceptions: they can include connection data.
        pass
    finally:
        url = ""
    try:
        protected_write(args.receipt, encoded(result))
    except Exception:
        return {
            "status": "RESULT_PERSISTENCE_FAILED",
            "observed_status": result["status"],
            "operation_id": package["operation_id"],
            "reason": "ATTEMPT_CONSUMED_RECONCILE_NO_RETRY",
        }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="offline dry validation unless --write-archive")
    prepare.add_argument("--package", required=True, type=Path)
    prepare.add_argument("--snapshot", required=True, type=Path)
    prepare.add_argument("--write-archive", action="store_true")
    prepare.add_argument("--archive", type=Path)
    prepare.add_argument("--manifest", type=Path)
    apply = commands.add_parser("apply", help="dry validation unless --enable-apply")
    apply.add_argument("--enable-apply", action="store_true")
    apply.add_argument("--credential-env")
    apply.add_argument("--receipt", type=Path)
    reconcile = commands.add_parser("reconcile", help="offline classification of an explicit observed state file")
    reconcile.add_argument("--state-observation", required=True, type=Path)
    for command in (apply, reconcile):
        command.add_argument("--archive", required=True, type=Path)
        command.add_argument("--manifest", required=True, type=Path)
    try:
        result = execute(parser.parse_args(argv))
    except ImportHoldError as exc:
        result = {"status": "HOLD", "reason": str(exc)}
    except Exception:
        result = {"status": "HOLD", "reason": "LOCAL_IO_OR_PACKAGE_FAILURE"}
    print(encoded(result).decode("utf-8"))
    return (
        0
        if result["status"]
        in {
            "PREPARED",
            "DRY_PREPARED_NO_WRITES",
            "DRY_APPLY_VALIDATED_NO_CONNECTION",
            "COMMITTED",
            "COMMITTED_PROVENANCE_OBSERVED",
        }
        else 3
    )


if __name__ == "__main__":
    raise SystemExit(main())
