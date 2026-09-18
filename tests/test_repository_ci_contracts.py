"""Failure cases for repository checks moved out of the legacy manual CI."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.ci import check_repository_contracts as contracts


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for directory in ("schemas", "config", "dashboard", "ea_interface", "execution"):
        (tmp_path / directory).mkdir()
    for name in contracts.SCHEMAS:
        (tmp_path / name).write_text(json.dumps({"type": "object", "properties": {}}), encoding="utf-8")
    (tmp_path / "config/settings.yaml").write_text("enabled: true\n", encoding="utf-8")
    for directory in contracts.BOUNDARIES:
        (tmp_path / directory / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(
        contracts,
        "_tracked_files",
        lambda root: sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()),
    )
    return tmp_path


def rules(repository: Path) -> set[str]:
    return {finding.rule for finding in contracts.check_repository(repository)}


def test_valid_repository_passes(repository: Path) -> None:
    assert contracts.check_repository(repository) == []


@pytest.mark.parametrize("name", contracts.SCHEMAS)
@pytest.mark.parametrize("content", ["{", '{"type": "not-a-json-schema-type"}'])
def test_malformed_or_invalid_schema_fails(repository: Path, name: str, content: str) -> None:
    (repository / name).write_text(content, encoding="utf-8")
    assert "schema-invalid" in rules(repository)


@pytest.mark.parametrize("name", contracts.SCHEMAS)
def test_missing_schema_fails(repository: Path, name: str) -> None:
    (repository / name).unlink()
    assert "schema-unreadable" in rules(repository)


def test_missing_required_directory_fails(repository: Path) -> None:
    (repository / "ea_interface/__init__.py").unlink()
    (repository / "ea_interface").rmdir()
    assert "required-directory-missing" in rules(repository)


def test_nested_config_yaml_is_parsed_and_errors_are_redacted(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    nested = repository / "config/nested"
    nested.mkdir()
    (nested / "test.yml").write_text("secret: [DO_NOT_PRINT_THIS\n", encoding="utf-8")
    assert contracts.main(["--root", str(repository)]) == 1
    output = capsys.readouterr().out
    assert "config-yaml-invalid" in output
    assert "DO_NOT_PRINT_THIS" not in output


@pytest.mark.parametrize(
    "directory, forbidden", [(key, item) for key, values in contracts.BOUNDARIES.items() for item in values]
)
def test_legacy_boundary_violation_fails(repository: Path, directory: str, forbidden: str) -> None:
    (repository / directory / "boundary.py").write_text(f"def {forbidden}():\n    return None\n", encoding="utf-8")
    findings = contracts.check_repository(repository)
    assert contracts.Finding("layer-boundary-violation", f"{directory}/boundary.py", 1) in findings


@pytest.mark.parametrize("comment", ["# pyright: ignore", "# pyright: ignore # explanation", "# pyright: ignore[]"])
def test_blanket_ignores_in_comments_fail(repository: Path, comment: str) -> None:
    (repository / "example.py").write_text(f"value = 1  {comment}\n", encoding="utf-8")
    assert "blanket-pyright-ignore" in rules(repository)


def test_specific_ignores_and_string_fixtures_are_allowed(repository: Path) -> None:
    (repository / "example.py").write_text(
        'fixture = "# pyright: ignore"\n'
        'doc = """fixture\n# pyright: ignore\n"""\n'
        "value = 1  # pyright: ignore[reportArgumentType]\n"
        "other = 2  # pyright: ignore[reportArgumentType, reportOptionalMemberAccess] # explanation\n",
        encoding="utf-8",
    )
    assert contracts.check_repository(repository) == []


def test_unreadable_tracked_python_fails(repository: Path) -> None:
    (repository / "example.py").write_bytes(b"\xff")
    assert "source-unreadable" in rules(repository)


def test_python_tokenization_failure_is_not_suppressed(repository: Path) -> None:
    (repository / "example.py").write_text('value = """unfinished\n', encoding="utf-8")
    assert "python-tokenization-failed" in rules(repository)


@pytest.mark.parametrize("name", sorted(contracts.BUILD_ARTIFACTS))
def test_tracked_build_artifacts_fail(repository: Path, name: str) -> None:
    (repository / "config" / name).write_text("fixture", encoding="utf-8")
    assert "committed-build-artifact" in rules(repository)


def test_coverage_configuration_is_allowed(repository: Path) -> None:
    (repository / ".coveragerc").write_text("[run]\nbranch = True\n", encoding="utf-8")
    assert contracts.check_repository(repository) == []


def test_untracked_generated_artifacts_are_ignored(repository: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tracked = contracts._tracked_files(repository)
    (repository / "coverage.xml").write_text("generated report", encoding="utf-8")
    monkeypatch.setattr(contracts, "_tracked_files", lambda root: tracked)
    assert contracts.check_repository(repository) == []


def test_git_error_fails_without_leaking_stderr(
    repository: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unavailable(root: Path) -> list[str]:
        raise subprocess.CalledProcessError(128, ["git"], stderr="DO_NOT_PRINT_THIS")

    monkeypatch.setattr(contracts, "_tracked_files", unavailable)
    assert contracts.main(["--root", str(repository)]) == 1
    output = capsys.readouterr().out
    assert "tracked-files-unavailable" in output
    assert "DO_NOT_PRINT_THIS" not in output


def test_empty_index_cannot_pass(repository: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(contracts, "_tracked_files", lambda root: [])
    assert "tracked-files-empty" in rules(repository)


def test_output_escapes_path_control_characters() -> None:
    output = contracts.Finding("example", "config/name\n::error::injected.yml", 2).diagnostic()
    assert "\n" not in output
    assert "\\n" in output
