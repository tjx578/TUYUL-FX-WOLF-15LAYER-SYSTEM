from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from journal import forensic_replay
from journal.forensic_replay import (
    FORENSIC_ARTIFACTS_PATH,
    FORENSIC_ARTIFACTS_PATH_ENV,
    MINIMUM_REPLAY_ARTIFACTS,
    ForensicArtifactPathError,
    append_replay_artifact,
    reconstruct_incident,
)

ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def _configured_override(
    monkeypatch: pytest.MonkeyPatch,
    trusted_root: Path,
    configured: str,
) -> Iterator[None]:
    previous_root = forensic_replay._set_forensic_artifacts_trusted_root(trusted_root)
    with monkeypatch.context() as scoped:
        scoped.setenv(FORENSIC_ARTIFACTS_PATH_ENV, configured)
        try:
            yield
        finally:
            forensic_replay._set_forensic_artifacts_trusted_root(previous_root)


def _create_directory_link(link: Path, target: Path) -> str:
    link_kind = "symlink"
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError as exc:
        if os.name != "nt":
            pytest.skip(f"POSIX symlink unavailable: {type(exc).__name__}")
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            pytest.skip(f"Windows junction unavailable: returncode={result.returncode}")
        link_kind = "junction"
    return link_kind


def _remove_directory_link(link: Path, link_kind: str) -> None:
    if os.path.lexists(link):
        if link_kind == "junction":
            os.rmdir(link)
        else:
            link.unlink()


@contextmanager
def _directory_link(link: Path, target: Path) -> Iterator[str]:
    link_kind = _create_directory_link(link, target)

    try:
        yield link_kind
    finally:
        _remove_directory_link(link, link_kind)


def _append_audit_line(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, separators=(",", ":")) + "\n")


def test_unset_override_preserves_default_path(monkeypatch: pytest.MonkeyPatch) -> None:
    with monkeypatch.context() as scoped:
        scoped.delenv(FORENSIC_ARTIFACTS_PATH_ENV, raising=False)
        assert forensic_replay._default_forensic_artifacts_path() == FORENSIC_ARTIFACTS_PATH


def test_valid_relative_descendant_writes_inside_trusted_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()

    with _configured_override(monkeypatch, trusted_root, "nested/replay.jsonl"):
        append_replay_artifact("event_history", correlation_id="bounded", payload={"ok": True})

    target = trusted_root / "nested" / "replay.jsonl"
    assert target.is_file()
    assert json.loads(target.read_text(encoding="utf-8"))["correlation_id"] == "bounded"


def test_absolute_override_is_rejected_without_touching_external_sentinel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trusted_root = tmp_path / "trusted"
    external_root = tmp_path / "external"
    trusted_root.mkdir()
    external_root.mkdir()
    sentinel = external_root / "sentinel.bin"
    expected = b"wolf15-r4-external-sentinel"
    sentinel.write_bytes(expected)

    with (
        _configured_override(monkeypatch, trusted_root, str(sentinel)),
        pytest.raises(ForensicArtifactPathError) as error,
    ):
        append_replay_artifact("event_history", correlation_id="absolute", payload={})

    assert str(error.value) == "FORENSIC_ARTIFACT_OVERRIDE_ROOTED"
    assert str(sentinel) not in str(error.value)
    assert sentinel.read_bytes() == expected


def test_parent_traversal_is_rejected_before_directory_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()
    escaped_parent = tmp_path / "escaped-parent"

    with (
        _configured_override(monkeypatch, trusted_root, "../escaped-parent/replay.jsonl"),
        pytest.raises(ForensicArtifactPathError, match="^FORENSIC_ARTIFACT_OVERRIDE_TRAVERSAL$"),
    ):
        append_replay_artifact("event_history", correlation_id="traversal", payload={})

    assert not escaped_parent.exists()


def test_nested_traversal_is_rejected_before_directory_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()
    escaped_parent = tmp_path / "nested-escape"

    with (
        _configured_override(monkeypatch, trusted_root, "a/../../nested-escape/replay.jsonl"),
        pytest.raises(ForensicArtifactPathError, match="^FORENSIC_ARTIFACT_OVERRIDE_TRAVERSAL$"),
    ):
        append_replay_artifact("event_history", correlation_id="nested", payload={})

    assert not escaped_parent.exists()


@pytest.mark.parametrize(
    "configured",
    [
        "",
        "   ",
        r"C:\outside\replay.jsonl",
        r"C:outside\replay.jsonl",
        r"\\server\share\replay.jsonl",
        r"\\?\C:\outside\replay.jsonl",
        r"\outside\replay.jsonl",
        "/outside/replay.jsonl",
        "NUL",
        "COM¹.txt",
        "COM².txt",
        "COM³.txt",
        "LPT¹.txt",
        "LPT².txt",
        "LPT³.txt",
        "nested/replay.jsonl:stream",
    ],
)
def test_ambiguous_rooted_and_device_overrides_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    configured: str,
) -> None:
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()

    with (
        _configured_override(monkeypatch, trusted_root, configured),
        pytest.raises(ForensicArtifactPathError) as error,
    ):
        append_replay_artifact("event_history", correlation_id="invalid", payload={})

    assert str(error.value).startswith("FORENSIC_ARTIFACT_")
    if configured:
        assert configured not in str(error.value)


def test_sibling_prefix_collision_through_link_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trusted_root = tmp_path / "ledger"
    sibling_root = tmp_path / "ledger-sibling"
    trusted_root.mkdir()
    sibling_root.mkdir()
    sentinel = sibling_root / "sentinel.bin"
    expected = b"sibling-prefix-sentinel"
    sentinel.write_bytes(expected)
    link = trusted_root / "redirect"

    with (
        _directory_link(link, sibling_root) as link_kind,
        _configured_override(monkeypatch, trusted_root, "redirect/sentinel.bin"),
        pytest.raises(
            ForensicArtifactPathError,
            match="^FORENSIC_ARTIFACT_PATH_REPARSE_POINT$",
        ),
    ):
        append_replay_artifact("event_history", correlation_id="prefix", payload={})
        assert link_kind == ("junction" if os.name == "nt" else "symlink")

    assert sentinel.read_bytes() == expected


def test_linked_parent_is_rejected_even_when_target_stays_inside_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trusted_root = tmp_path / "trusted"
    real_parent = trusted_root / "real-parent"
    trusted_root.mkdir()
    real_parent.mkdir()
    link = trusted_root / "linked-parent"

    with (
        _directory_link(link, real_parent),
        _configured_override(monkeypatch, trusted_root, "linked-parent/replay.jsonl"),
        pytest.raises(
            ForensicArtifactPathError,
            match="^FORENSIC_ARTIFACT_PATH_REPARSE_POINT$",
        ),
    ):
        append_replay_artifact("event_history", correlation_id="internal-link", payload={})

    assert not (real_parent / "replay.jsonl").exists()


def test_post_validation_link_swap_is_blocked_by_handle_safe_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trusted_root = tmp_path / "trusted"
    raced_parent = trusted_root / "raced-parent"
    external_root = tmp_path / "external"
    trusted_root.mkdir()
    raced_parent.mkdir()
    external_root.mkdir()
    sentinel = external_root / "sentinel.bin"
    expected = b"post-validation-race-sentinel"
    sentinel.write_bytes(expected)
    original_resolver = forensic_replay._resolve_forensic_artifact_override
    link_kind: str | None = None

    def _resolve_then_swap(configured: str) -> Path:
        nonlocal link_kind
        target = original_resolver(configured)
        raced_parent.rmdir()
        link_kind = _create_directory_link(raced_parent, external_root)
        return target

    monkeypatch.setattr(forensic_replay, "_resolve_forensic_artifact_override", _resolve_then_swap)
    try:
        with (
            _configured_override(monkeypatch, trusted_root, "raced-parent/replay.jsonl"),
            patch.object(forensic_replay.logger, "warning") as warning,
        ):
            entry = append_replay_artifact(
                "event_history",
                correlation_id="post-validation-race",
                payload={},
            )
    finally:
        if link_kind is not None:
            _remove_directory_link(raced_parent, link_kind)

    warning.assert_called_once()
    assert entry["correlation_id"] == "post-validation-race"
    assert sentinel.read_bytes() == expected
    assert not (external_root / "replay.jsonl").exists()


def test_hard_link_alias_is_rejected_without_touching_external_sentinel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trusted_root = tmp_path / "trusted"
    external_root = tmp_path / "external"
    trusted_root.mkdir()
    external_root.mkdir()
    sentinel = external_root / "sentinel.bin"
    expected = b"hard-link-external-sentinel"
    sentinel.write_bytes(expected)
    alias = trusted_root / "replay.jsonl"
    try:
        os.link(sentinel, alias)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {type(exc).__name__}")

    with (
        _configured_override(monkeypatch, trusted_root, alias.name),
        patch.object(forensic_replay.logger, "warning") as warning,
    ):
        entry = append_replay_artifact(
            "event_history",
            correlation_id="hard-link-alias",
            payload={},
        )

    warning.assert_called_once()
    assert entry["correlation_id"] == "hard-link-alias"
    assert sentinel.read_bytes() == expected
    assert alias.read_bytes() == expected


if os.name != "nt" and hasattr(os, "mkfifo"):

    def test_posix_fifo_target_fails_closed_without_blocking(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        trusted_root = tmp_path / "trusted"
        trusted_root.mkdir()
        fifo = trusted_root / "replay.jsonl"
        os.mkfifo(fifo)

        with (
            _configured_override(monkeypatch, trusted_root, fifo.name),
            patch.object(forensic_replay.logger, "warning") as warning,
        ):
            entry = append_replay_artifact(
                "event_history",
                correlation_id="fifo-target",
                payload={},
            )

        warning.assert_called_once()
        assert entry["correlation_id"] == "fifo-target"
        assert stat.S_ISFIFO(fifo.lstat().st_mode)


def test_missing_trusted_root_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    previous_root = forensic_replay._set_forensic_artifacts_trusted_root(None)
    try:
        with monkeypatch.context() as scoped:
            scoped.setenv(FORENSIC_ARTIFACTS_PATH_ENV, "replay.jsonl")
            with pytest.raises(
                ForensicArtifactPathError,
                match="^FORENSIC_ARTIFACT_TRUSTED_ROOT_MISSING$",
            ):
                append_replay_artifact("event_history", correlation_id="missing-root", payload={})
    finally:
        forensic_replay._set_forensic_artifacts_trusted_root(previous_root)


def test_removed_trusted_root_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trusted_root = tmp_path / "removed-root"
    trusted_root.mkdir()
    previous_root = forensic_replay._set_forensic_artifacts_trusted_root(trusted_root)
    trusted_root.rmdir()
    try:
        with monkeypatch.context() as scoped:
            scoped.setenv(FORENSIC_ARTIFACTS_PATH_ENV, "replay.jsonl")
            with pytest.raises(
                ForensicArtifactPathError,
                match="^FORENSIC_ARTIFACT_TRUSTED_ROOT_INVALID$",
            ):
                append_replay_artifact("event_history", correlation_id="removed-root", payload={})
    finally:
        forensic_replay._set_forensic_artifacts_trusted_root(previous_root)

    assert not trusted_root.exists()


def test_file_cannot_be_injected_as_trusted_root(tmp_path: Path) -> None:
    root_file = tmp_path / "not-a-directory"
    expected = b"root-file-sentinel"
    root_file.write_bytes(expected)

    with pytest.raises(
        ForensicArtifactPathError,
        match="^FORENSIC_ARTIFACT_TRUSTED_ROOT_NOT_DIRECTORY$",
    ):
        forensic_replay._set_forensic_artifacts_trusted_root(root_file)

    assert root_file.read_bytes() == expected


def test_unwritable_bounded_target_preserves_existing_append_failure_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()
    target = trusted_root / "unwritable.jsonl"
    target.mkdir()

    with (
        _configured_override(monkeypatch, trusted_root, target.name),
        patch.object(forensic_replay.logger, "warning") as warning,
    ):
        entry = append_replay_artifact(
            "event_history",
            correlation_id="unwritable",
            payload={"expected": "best-effort-return"},
        )

    warning.assert_called_once()
    assert entry["correlation_id"] == "unwritable"
    assert target.is_dir()


def test_repeated_valid_appends_stay_in_one_bounded_ledger(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()

    with _configured_override(monkeypatch, trusted_root, "nested/replay.jsonl"):
        append_replay_artifact("event_history", correlation_id="first", payload={})
        append_replay_artifact("event_history", correlation_id="second", payload={})

    ledger = trusted_root / "nested" / "replay.jsonl"
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert [row["correlation_id"] for row in rows] == ["first", "second"]


def test_override_context_restores_environment_and_trusted_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline_env = os.environ.get(FORENSIC_ARTIFACTS_PATH_ENV)
    baseline_root = forensic_replay._FORENSIC_ARTIFACTS_TRUSTED_ROOT
    trusted_root = tmp_path / "temporary-root"
    trusted_root.mkdir()

    with _configured_override(monkeypatch, trusted_root, "temporary.jsonl"):
        assert os.environ[FORENSIC_ARTIFACTS_PATH_ENV] == "temporary.jsonl"
        assert trusted_root.resolve() == forensic_replay._FORENSIC_ARTIFACTS_TRUSTED_ROOT

    assert os.environ.get(FORENSIC_ARTIFACTS_PATH_ENV) == baseline_env
    assert baseline_root == forensic_replay._FORENSIC_ARTIFACTS_TRUSTED_ROOT


def test_reconstruct_incident_reports_complete_coverage(tmp_path: Path) -> None:
    artifact_log = tmp_path / "artifacts.jsonl"
    audit_log = tmp_path / "audit.jsonl"
    cid = "ei_complete_001"

    for artifact_type in MINIMUM_REPLAY_ARTIFACTS:
        append_replay_artifact(
            artifact_type,
            correlation_id=cid,
            payload={"artifact_type": artifact_type},
            log_path=artifact_log,
        )

    _append_audit_line(
        audit_log,
        {
            "timestamp": "2026-03-20T12:00:00+00:00",
            "action": "ORDER_PLACED",
            "resource": f"intent:{cid}",
            "details": {"execution_intent_id": cid},
        },
    )

    report = reconstruct_incident(cid, artifact_log_path=artifact_log, audit_log_path=audit_log)

    assert report["coverage"]["is_sufficient"] is True
    assert report["coverage"]["missing"] == []
    assert report["artifact_count"] == len(MINIMUM_REPLAY_ARTIFACTS)
    assert report["audit_count"] == 1
    assert len(report["timeline"]) >= len(MINIMUM_REPLAY_ARTIFACTS)


def test_reconstruct_incident_reports_missing_artifacts(tmp_path: Path) -> None:
    artifact_log = tmp_path / "artifacts.jsonl"
    cid = "ei_partial_001"

    append_replay_artifact(
        "verdict_provenance",
        correlation_id=cid,
        payload={"verdict": "EXECUTE"},
        log_path=artifact_log,
    )

    report = reconstruct_incident(cid, artifact_log_path=artifact_log, audit_log_path=tmp_path / "none.jsonl")

    assert report["coverage"]["is_sufficient"] is False
    assert "event_history" in report["coverage"]["missing"]
    assert "execution_lifecycle" in report["coverage"]["missing"]


def test_default_forensic_path_is_inherited_by_child_process(
    isolated_forensic_artifacts: Path,
) -> None:
    correlation_id = "subprocess_isolation_001"
    trusted_root = isolated_forensic_artifacts.parent
    code = (
        "from pathlib import Path; "
        "from journal import forensic_replay; "
        f"forensic_replay._set_forensic_artifacts_trusted_root(Path({str(trusted_root)!r})); "
        "forensic_replay.append_replay_artifact("
        f"'event_history', correlation_id={correlation_id!r}, payload={{'source': 'child'}})"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert not Path(os.environ[FORENSIC_ARTIFACTS_PATH_ENV]).is_absolute()
    assert correlation_id in isolated_forensic_artifacts.read_text(encoding="utf-8")
