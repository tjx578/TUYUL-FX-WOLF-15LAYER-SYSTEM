"""Append-only forensic replay artifacts for RCA reconstruction.

Zone: journal. This module has no decision authority and only records facts.
"""

from __future__ import annotations

import json
import os
import stat
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, TextIO, cast

from loguru import logger

FORENSIC_ARTIFACTS_PATH_ENV = "WOLF15_FORENSIC_ARTIFACTS_PATH"
FORENSIC_ARTIFACTS_PATH = Path("storage/forensics/replay_artifacts.jsonl")
AUDIT_TRAIL_PATH = Path("storage/audit/audit_trail.jsonl")

_FORENSIC_ARTIFACTS_TRUSTED_ROOT: Path | None = None
_WINDOWS_RESERVED_DEVICE_NAMES = frozenset(
    {
        "AUX",
        "CON",
        "NUL",
        "PRN",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
        *(f"COM{index}" for index in ("¹", "²", "³")),
        *(f"LPT{index}" for index in ("¹", "²", "³")),
    }
)

MINIMUM_REPLAY_ARTIFACTS: tuple[str, ...] = (
    "event_history",
    "verdict_provenance",
    "firewall_result",
    "execution_lifecycle",
    "freshness_snapshot",
)


class ForensicArtifactPathError(ValueError):
    """Raised when an artifact override cannot be contained safely."""


def _path_components(path: Path) -> tuple[Path, ...]:
    current = Path(path.anchor)
    components = [current]
    for part in path.parts[1:]:
        current /= part
        components.append(current)
    return tuple(components)


def _assert_no_reparse_points(path: Path) -> None:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    for component in _path_components(path):
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            break
        except OSError:
            raise ForensicArtifactPathError("FORENSIC_ARTIFACT_PATH_UNINSPECTABLE") from None

        file_attributes = getattr(metadata, "st_file_attributes", 0)
        if stat.S_ISLNK(metadata.st_mode) or bool(file_attributes & reparse_flag):
            raise ForensicArtifactPathError("FORENSIC_ARTIFACT_PATH_REPARSE_POINT")


def _resolve_trusted_forensic_root(root: Path) -> Path:
    if not root.is_absolute():
        raise ForensicArtifactPathError("FORENSIC_ARTIFACT_TRUSTED_ROOT_NOT_ABSOLUTE")
    if os.name == "nt" and root.anchor.startswith("\\\\"):
        raise ForensicArtifactPathError("FORENSIC_ARTIFACT_TRUSTED_ROOT_NOT_LOCAL")

    _assert_no_reparse_points(root)
    try:
        resolved = root.resolve(strict=True)
    except (OSError, RuntimeError):
        raise ForensicArtifactPathError("FORENSIC_ARTIFACT_TRUSTED_ROOT_INVALID") from None
    if not resolved.is_dir():
        raise ForensicArtifactPathError("FORENSIC_ARTIFACT_TRUSTED_ROOT_NOT_DIRECTORY")
    _assert_no_reparse_points(resolved)
    return resolved


def _set_forensic_artifacts_trusted_root(root: Path | None) -> Path | None:
    """Inject a process-local root owned by a disposable test lifecycle."""
    global _FORENSIC_ARTIFACTS_TRUSTED_ROOT

    previous = _FORENSIC_ARTIFACTS_TRUSTED_ROOT
    _FORENSIC_ARTIFACTS_TRUSTED_ROOT = None if root is None else _resolve_trusted_forensic_root(Path(root))
    return previous


def _validate_relative_artifact_path(configured: str) -> Path:
    if not configured or configured != configured.strip():
        raise ForensicArtifactPathError("FORENSIC_ARTIFACT_OVERRIDE_EMPTY_OR_PADDED")
    if any(ord(character) < 32 for character in configured):
        raise ForensicArtifactPathError("FORENSIC_ARTIFACT_OVERRIDE_CONTROL_CHARACTER")

    windows_path = PureWindowsPath(configured)
    posix_path = PurePosixPath(configured)
    if windows_path.drive or windows_path.root or posix_path.root:
        raise ForensicArtifactPathError("FORENSIC_ARTIFACT_OVERRIDE_ROOTED")
    if ".." in windows_path.parts or ".." in posix_path.parts:
        raise ForensicArtifactPathError("FORENSIC_ARTIFACT_OVERRIDE_TRAVERSAL")
    if os.name != "nt" and "\\" in configured:
        raise ForensicArtifactPathError("FORENSIC_ARTIFACT_OVERRIDE_AMBIGUOUS_SEPARATOR")

    for part in windows_path.parts:
        normalized = part.rstrip(" .")
        device_name = normalized.split(".", maxsplit=1)[0].upper()
        if normalized != part or ":" in part or device_name in _WINDOWS_RESERVED_DEVICE_NAMES:
            raise ForensicArtifactPathError("FORENSIC_ARTIFACT_OVERRIDE_WINDOWS_DEVICE")

    relative_path = Path(configured)
    if not relative_path.parts:
        raise ForensicArtifactPathError("FORENSIC_ARTIFACT_OVERRIDE_EMPTY_OR_PADDED")
    return relative_path


def _resolve_forensic_artifact_override(configured: str) -> Path:
    trusted_root = _FORENSIC_ARTIFACTS_TRUSTED_ROOT
    if trusted_root is None:
        raise ForensicArtifactPathError("FORENSIC_ARTIFACT_TRUSTED_ROOT_MISSING")
    trusted_root = _resolve_trusted_forensic_root(trusted_root)
    relative_path = _validate_relative_artifact_path(configured)
    candidate = trusted_root / relative_path

    _assert_no_reparse_points(candidate)
    try:
        resolved_candidate = candidate.resolve(strict=False)
        relative_candidate = resolved_candidate.relative_to(trusted_root)
    except (OSError, RuntimeError, ValueError):
        raise ForensicArtifactPathError("FORENSIC_ARTIFACT_OVERRIDE_ESCAPE") from None
    if not relative_candidate.parts:
        raise ForensicArtifactPathError("FORENSIC_ARTIFACT_OVERRIDE_EQUALS_ROOT")
    return resolved_candidate


@contextmanager
def _open_posix_bounded_append(trusted_root: Path, relative_path: Path) -> Iterator[TextIO]:
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise ForensicArtifactPathError("FORENSIC_ARTIFACT_SECURE_OPEN_UNAVAILABLE")
    os_flags = vars(os)
    directory_flag = int(os_flags["O_DIRECTORY"])
    no_follow_flag = int(os_flags["O_NOFOLLOW"])
    directory_flags = os.O_RDONLY | directory_flag | no_follow_flag
    directory_fds: list[int] = []
    file_fd: int | None = None
    try:
        current_fd = os.open(trusted_root.anchor, directory_flags)
        directory_fds.append(current_fd)
        for part in trusted_root.parts[1:]:
            current_fd = os.open(part, directory_flags, dir_fd=current_fd)
            directory_fds.append(current_fd)

        for part in relative_path.parts[:-1]:
            try:
                child_fd = os.open(part, directory_flags, dir_fd=current_fd)
            except FileNotFoundError:
                with suppress(FileExistsError):
                    os.mkdir(part, mode=0o700, dir_fd=current_fd)
                child_fd = os.open(part, directory_flags, dir_fd=current_fd)
            current_fd = child_fd
            directory_fds.append(current_fd)

        file_fd = os.open(
            relative_path.name,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | no_follow_flag | int(getattr(os, "O_NONBLOCK", 0)),
            0o600,
            dir_fd=current_fd,
        )
        file_metadata = os.fstat(file_fd)
        if not stat.S_ISREG(file_metadata.st_mode):
            raise ForensicArtifactPathError("FORENSIC_ARTIFACT_TARGET_NOT_REGULAR")
        if file_metadata.st_nlink != 1:
            raise ForensicArtifactPathError("FORENSIC_ARTIFACT_TARGET_LINKED")
        with os.fdopen(file_fd, "a", encoding="utf-8") as handle:
            file_fd = None
            yield handle
    finally:
        if file_fd is not None:
            os.close(file_fd)
        for directory_fd in reversed(directory_fds):
            os.close(directory_fd)


@contextmanager
def _open_windows_bounded_append(trusted_root: Path, relative_path: Path) -> Iterator[TextIO]:
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    file_attribute_directory = 0x00000010
    file_attribute_device = 0x00000040
    file_attribute_normal = 0x00000080
    file_attribute_reparse_point = 0x00000400
    file_append_data = 0x00000004
    file_flag_backup_semantics = 0x02000000
    file_flag_open_reparse_point = 0x00200000
    file_read_attributes = 0x00000080
    file_traverse = 0x00000020
    file_share_read = 0x00000001
    file_directory_file = 0x00000001
    file_non_directory_file = 0x00000040
    file_open_reparse_point = 0x00200000
    file_synchronous_io_nonalert = 0x00000020
    file_create = 2
    file_open = 1
    synchronize = 0x00100000
    open_existing = 3
    file_attribute_tag_info_class = 9
    object_case_insensitive = 0x00000040
    invalid_handle_value = ctypes.c_void_p(-1).value

    class FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [("file_attributes", wintypes.DWORD), ("reparse_tag", wintypes.DWORD)]

    class ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("file_attributes", wintypes.DWORD),
            ("creation_time", wintypes.FILETIME),
            ("last_access_time", wintypes.FILETIME),
            ("last_write_time", wintypes.FILETIME),
            ("volume_serial_number", wintypes.DWORD),
            ("file_size_high", wintypes.DWORD),
            ("file_size_low", wintypes.DWORD),
            ("number_of_links", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD),
            ("file_index_low", wintypes.DWORD),
        ]

    class UnicodeString(ctypes.Structure):
        _fields_ = [
            ("length", wintypes.USHORT),
            ("maximum_length", wintypes.USHORT),
            ("buffer", wintypes.LPWSTR),
        ]

    class ObjectAttributes(ctypes.Structure):
        _fields_ = [
            ("length", wintypes.ULONG),
            ("root_directory", wintypes.HANDLE),
            ("object_name", ctypes.POINTER(UnicodeString)),
            ("attributes", wintypes.ULONG),
            ("security_descriptor", wintypes.LPVOID),
            ("security_quality_of_service", wintypes.LPVOID),
        ]

    class IoStatusBlock(ctypes.Structure):
        _fields_ = [("status", ctypes.c_ssize_t), ("information", ctypes.c_size_t)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    get_handle_info = kernel32.GetFileInformationByHandleEx
    get_handle_info.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    get_handle_info.restype = wintypes.BOOL
    get_file_info = kernel32.GetFileInformationByHandle
    get_file_info.argtypes = (wintypes.HANDLE, ctypes.POINTER(ByHandleFileInformation))
    get_file_info.restype = wintypes.BOOL
    write_file = kernel32.WriteFile
    write_file.argtypes = (
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    write_file.restype = wintypes.BOOL
    flush_file_buffers = kernel32.FlushFileBuffers
    flush_file_buffers.argtypes = (wintypes.HANDLE,)
    flush_file_buffers.restype = wintypes.BOOL
    ntdll = ctypes.WinDLL("ntdll")
    nt_create_file = ntdll.NtCreateFile
    nt_create_file.argtypes = (
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        ctypes.POINTER(ObjectAttributes),
        ctypes.POINTER(IoStatusBlock),
        wintypes.LPVOID,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.LPVOID,
        wintypes.ULONG,
    )
    nt_create_file.restype = ctypes.c_long

    held_directories: list[int] = []
    file_handle: int | None = None

    class WindowsAppendStream:
        def __init__(self, handle: int) -> None:
            self._handle = handle

        def write(self, value: str) -> int:
            payload = value.encode("utf-8")
            buffer = ctypes.create_string_buffer(payload)
            written = wintypes.DWORD()
            if not write_file(
                self._handle,
                buffer,
                len(payload),
                ctypes.byref(written),
                None,
            ):
                raise OSError("FORENSIC_ARTIFACT_TARGET_WRITE_FAILED")
            if written.value != len(payload):
                raise OSError("FORENSIC_ARTIFACT_TARGET_SHORT_WRITE")
            return len(value)

        def flush(self) -> None:
            if not flush_file_buffers(self._handle):
                raise OSError("FORENSIC_ARTIFACT_TARGET_FLUSH_FAILED")

    def _inspect_component(handle: int, *, directory: bool) -> None:
        info = FileAttributeTagInfo()
        if not get_handle_info(
            handle,
            file_attribute_tag_info_class,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            raise OSError("FORENSIC_ARTIFACT_TARGET_INSPECTION_FAILED")
        if info.file_attributes & file_attribute_reparse_point:
            raise ForensicArtifactPathError("FORENSIC_ARTIFACT_PATH_REPARSE_POINT")
        if directory and not info.file_attributes & file_attribute_directory:
            raise ForensicArtifactPathError("FORENSIC_ARTIFACT_PARENT_NOT_DIRECTORY")
        if not directory:
            file_info = ByHandleFileInformation()
            if not get_file_info(handle, ctypes.byref(file_info)):
                raise OSError("FORENSIC_ARTIFACT_TARGET_INSPECTION_FAILED")
            invalid_attributes = file_attribute_device | file_attribute_directory | file_attribute_reparse_point
            if file_info.file_attributes & invalid_attributes:
                raise ForensicArtifactPathError("FORENSIC_ARTIFACT_TARGET_NOT_REGULAR")
            if file_info.number_of_links != 1:
                raise ForensicArtifactPathError("FORENSIC_ARTIFACT_TARGET_LINKED")

    def _call_nt_create(
        parent_handle: int,
        name: str,
        *,
        desired_access: int,
        disposition: int,
        options: int,
        attributes: int,
    ) -> int | None:
        name_buffer = ctypes.create_unicode_buffer(name)
        name_length = len(name.encode("utf-16-le"))
        object_name = UnicodeString(
            length=name_length,
            maximum_length=ctypes.sizeof(name_buffer),
            buffer=ctypes.cast(name_buffer, wintypes.LPWSTR),
        )
        object_attributes = ObjectAttributes(
            length=ctypes.sizeof(ObjectAttributes),
            root_directory=wintypes.HANDLE(parent_handle),
            object_name=ctypes.pointer(object_name),
            attributes=object_case_insensitive,
            security_descriptor=None,
            security_quality_of_service=None,
        )
        io_status = IoStatusBlock()
        result_handle = wintypes.HANDLE()
        status = nt_create_file(
            ctypes.byref(result_handle),
            desired_access,
            ctypes.byref(object_attributes),
            ctypes.byref(io_status),
            None,
            attributes,
            file_share_read,
            disposition,
            options,
            None,
            0,
        )
        if status < 0 or result_handle.value is None:
            return None
        return int(result_handle.value)

    def _open_relative_component(
        parent_handle: int,
        name: str,
        *,
        directory: bool,
        create: bool,
    ) -> int:
        desired_access = synchronize | file_read_attributes | (file_traverse if directory else file_append_data)
        handle = _call_nt_create(
            parent_handle,
            name,
            desired_access=desired_access,
            disposition=file_open,
            options=file_open_reparse_point | file_synchronous_io_nonalert,
            attributes=0,
        )
        if handle is None and create:
            handle = _call_nt_create(
                parent_handle,
                name,
                desired_access=desired_access,
                disposition=file_create,
                options=(file_directory_file if directory else file_non_directory_file) | file_synchronous_io_nonalert,
                attributes=0 if directory else file_attribute_normal,
            )
        if handle is None:
            raise OSError("FORENSIC_ARTIFACT_TARGET_OPEN_FAILED")
        try:
            _inspect_component(handle, directory=directory)
        except Exception:
            close_handle(handle)
            raise
        return handle

    try:
        volume_root = create_file(
            trusted_root.anchor,
            file_read_attributes | file_traverse,
            file_share_read,
            None,
            open_existing,
            file_flag_backup_semantics | file_flag_open_reparse_point,
            None,
        )
        if volume_root == invalid_handle_value:
            raise OSError("FORENSIC_ARTIFACT_TARGET_OPEN_FAILED")
        volume_root = int(volume_root)
        try:
            _inspect_component(volume_root, directory=True)
        except Exception:
            close_handle(volume_root)
            raise
        held_directories.append(volume_root)

        for part in trusted_root.parts[1:]:
            held_directories.append(_open_relative_component(held_directories[-1], part, directory=True, create=False))

        for part in relative_path.parts[:-1]:
            held_directories.append(_open_relative_component(held_directories[-1], part, directory=True, create=True))

        file_handle = _open_relative_component(
            held_directories[-1],
            relative_path.name,
            directory=False,
            create=True,
        )
        yield cast(TextIO, WindowsAppendStream(file_handle))
    finally:
        if file_handle is not None:
            close_handle(file_handle)
        for directory_handle in reversed(held_directories):
            close_handle(directory_handle)


@contextmanager
def _open_bounded_forensic_append(target: Path) -> Iterator[TextIO]:
    trusted_root = _FORENSIC_ARTIFACTS_TRUSTED_ROOT
    if trusted_root is None:
        raise ForensicArtifactPathError("FORENSIC_ARTIFACT_TRUSTED_ROOT_MISSING")
    trusted_root = _resolve_trusted_forensic_root(trusted_root)
    try:
        relative_path = target.relative_to(trusted_root)
    except ValueError:
        raise ForensicArtifactPathError("FORENSIC_ARTIFACT_OVERRIDE_ESCAPE") from None
    if not relative_path.parts:
        raise ForensicArtifactPathError("FORENSIC_ARTIFACT_OVERRIDE_EQUALS_ROOT")

    opener = _open_windows_bounded_append if os.name == "nt" else _open_posix_bounded_append
    with opener(trusted_root, relative_path) as handle:
        yield handle


@contextmanager
def _open_legacy_forensic_append(target: Path) -> Iterator[TextIO]:
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a", encoding="utf-8") as handle:
        yield handle


def _default_forensic_artifacts_path() -> Path:
    """Resolve the default forensic ledger, including process-safe overrides."""
    configured = os.getenv(FORENSIC_ARTIFACTS_PATH_ENV)
    if configured is None:
        return FORENSIC_ARTIFACTS_PATH
    return _resolve_forensic_artifact_override(configured)


def append_replay_artifact(
    artifact_type: str,
    *,
    correlation_id: str | None,
    payload: dict[str, Any],
    log_path: Path | None = None,
) -> dict[str, Any]:
    """Append one immutable forensic artifact entry.

    The write path is append-only JSONL by design. Any failure is logged and
    should not affect caller flow.
    """
    bounded_override = log_path is None and os.getenv(FORENSIC_ARTIFACTS_PATH_ENV) is not None
    target = log_path or _default_forensic_artifacts_path()
    entry = {
        "artifact_id": f"rfa_{uuid.uuid4().hex[:16]}",
        "captured_at": datetime.now(UTC).isoformat(),
        "artifact_type": str(artifact_type),
        "correlation_id": (str(correlation_id).strip() if correlation_id else None),
        "payload": payload,
    }

    try:
        target_context = (
            _open_bounded_forensic_append(target) if bounded_override else _open_legacy_forensic_append(target)
        )
        with target_context as handle:
            handle.write(json.dumps(entry, separators=(",", ":"), ensure_ascii=False) + "\n")
            handle.flush()
    except Exception as exc:  # pragma: no cover - best effort path
        logger.warning("Forensic artifact append failed: {}", exc)

    return entry


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    records.append(parsed)
    except Exception as exc:  # pragma: no cover - best effort path
        logger.warning("Forensic replay load failed for {}: {}", path, exc)
    return records


def load_replay_artifacts(*, log_path: Path | None = None) -> list[dict[str, Any]]:
    """Read immutable replay artifacts from JSONL store."""
    return _load_jsonl(log_path or _default_forensic_artifacts_path())


def load_audit_entries(*, log_path: Path | None = None) -> list[dict[str, Any]]:
    """Read append-only audit trail entries from JSONL store."""
    return _load_jsonl(log_path or AUDIT_TRAIL_PATH)


def _entry_ts(entry: dict[str, Any]) -> str:
    return str(entry.get("captured_at") or entry.get("timestamp") or "")


def _dedupe_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in entries:
        key = json.dumps(item, sort_keys=True, separators=(",", ":"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def reconstruct_incident(
    correlation_id: str,
    *,
    artifact_log_path: Path | None = None,
    audit_log_path: Path | None = None,
) -> dict[str, Any]:
    """Reconstruct an incident timeline from immutable forensic stores."""
    target = str(correlation_id).strip()
    if not target:
        raise ValueError("correlation_id is required")

    artifacts = load_replay_artifacts(log_path=artifact_log_path)
    matched = [a for a in artifacts if str(a.get("correlation_id") or "").strip() == target]

    by_type: dict[str, list[dict[str, Any]]] = {}
    for entry in matched:
        artifact_type = str(entry.get("artifact_type") or "unknown")
        by_type.setdefault(artifact_type, []).append(entry)

    audit_entries = load_audit_entries(log_path=audit_log_path)
    audit_related = [
        row
        for row in audit_entries
        if target
        in {
            str(row.get("resource") or ""),
            str((row.get("details") or {}).get("take_id") or ""),
            str((row.get("details") or {}).get("signal_id") or ""),
            str((row.get("details") or {}).get("execution_intent_id") or ""),
            str((row.get("details") or {}).get("trade_id") or ""),
        }
    ]

    timeline = _dedupe_entries(
        [
            {
                "timestamp": _entry_ts(a),
                "kind": "artifact",
                "artifact_type": a.get("artifact_type"),
                "correlation_id": a.get("correlation_id"),
                "payload": a.get("payload"),
            }
            for a in matched
        ]
        + [
            {
                "timestamp": str(row.get("timestamp") or ""),
                "kind": "audit",
                "action": row.get("action"),
                "resource": row.get("resource"),
                "details": row.get("details"),
            }
            for row in audit_related
        ]
    )
    timeline.sort(key=lambda item: str(item.get("timestamp") or ""))

    coverage = replay_coverage_report(matched)
    return {
        "correlation_id": target,
        "artifact_count": len(matched),
        "audit_count": len(audit_related),
        "artifacts_by_type": by_type,
        "coverage": coverage,
        "timeline": timeline,
    }


def replay_coverage_report(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Assess if minimum replay artifacts exist for an incident."""
    present = {str(e.get("artifact_type") or "") for e in entries}
    missing = [name for name in MINIMUM_REPLAY_ARTIFACTS if name not in present]
    return {
        "minimum_required": list(MINIMUM_REPLAY_ARTIFACTS),
        "present": sorted([p for p in present if p]),
        "missing": missing,
        "is_sufficient": len(missing) == 0,
    }
