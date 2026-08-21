from __future__ import annotations

import ast
import configparser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests" / "performance_gate_manifest.yaml"
ALLOWED_CLASSIFICATIONS = {
    "ABSOLUTE_PERFORMANCE",
    "MIXED_CORRECTNESS_PERFORMANCE",
    "HANG_GUARD",
}
ALLOWED_AUTHORITIES = {
    "PORTABLE_BLOCKING",
    "REFERENCE_RUNNER",
    "DIAGNOSTIC_ONLY",
}
REQUIRED_FIELDS = {
    "node_pattern",
    "source_file",
    "instance_count",
    "classification",
    "authority",
    "threshold",
    "current_marker",
    "target_marker",
    "correctness_companion",
    "notes",
}


@dataclass(frozen=True)
class FunctionRef:
    source_file: str
    class_name: str
    function_name: str


def _manifest() -> dict[str, Any]:
    payload = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _function_ref(node_pattern: str) -> FunctionRef:
    parts = node_pattern.split("::")
    assert len(parts) == 3, f"unsupported node pattern: {node_pattern}"
    source_file, class_name, function_name = parts
    return FunctionRef(
        source_file=source_file,
        class_name=class_name,
        function_name=function_name.removesuffix("[*]"),
    )


def _class_functions(source_file: str, class_name: str) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse((ROOT / source_file).read_text(encoding="utf-8"), filename=source_file)
    class_node = next(
        (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name),
        None,
    )
    assert class_node is not None, f"missing class {source_file}::{class_name}"
    return {node.name: node for node in class_node.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _function_node(node_pattern: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    ref = _function_ref(node_pattern)
    functions = _class_functions(ref.source_file, ref.class_name)
    assert ref.function_name in functions, f"missing test node: {node_pattern}"
    return functions[ref.function_name]


def _decorator_name(decorator: ast.expr) -> str:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return ast.unparse(target)


def _has_performance_marker(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(_decorator_name(decorator) == "pytest.mark.performance" for decorator in node.decorator_list)


def _instance_count(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    count = 1
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or _decorator_name(decorator) != "pytest.mark.parametrize":
            continue
        assert len(decorator.args) >= 2, f"invalid parametrize decorator on {node.name}"
        values = ast.literal_eval(decorator.args[1])
        count *= len(values)
    return count


def _performance_nodes_in_source(source_file: str) -> set[str]:
    tree = ast.parse((ROOT / source_file).read_text(encoding="utf-8"), filename=source_file)
    found: set[str] = set()
    for class_node in (node for node in tree.body if isinstance(node, ast.ClassDef)):
        for function_node in (
            node for node in class_node.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            if _has_performance_marker(function_node):
                found.add(f"{source_file}::{class_node.name}::{function_node.name}")
    return found


def test_manifest_has_exact_reviewed_counts_and_no_duplicates() -> None:
    payload = _manifest()
    definitions = payload["definitions"]
    hang_guards = payload["hang_guards"]
    counts = payload["counts"]

    assert counts == {
        "performance_definitions": 20,
        "performance_instances": 26,
        "explicit_hang_guard_definitions": 2,
    }
    assert len(definitions) == counts["performance_definitions"]
    assert sum(entry["instance_count"] for entry in definitions) == counts["performance_instances"]
    assert len(hang_guards) == counts["explicit_hang_guard_definitions"]

    entries = [*definitions, *hang_guards]
    assert all(entry.keys() >= REQUIRED_FIELDS for entry in entries)
    patterns = [entry["node_pattern"] for entry in entries]
    assert len(patterns) == len(set(patterns))
    assert all(entry["classification"] in ALLOWED_CLASSIFICATIONS for entry in entries)
    assert all(entry["authority"] in ALLOWED_AUTHORITIES for entry in entries)


def test_manifest_entries_resolve_and_account_for_parametrized_instances() -> None:
    payload = _manifest()
    for entry in [*payload["definitions"], *payload["hang_guards"]]:
        ref = _function_ref(entry["node_pattern"])
        assert entry["source_file"] == ref.source_file
        assert (ROOT / ref.source_file).is_file()
        node = _function_node(entry["node_pattern"])
        assert _instance_count(node) == entry["instance_count"]


def test_performance_marker_registry_matches_manifest_exactly() -> None:
    definitions = _manifest()["definitions"]
    expected = {
        entry["node_pattern"].removesuffix("[*]") for entry in definitions if entry["target_marker"] == "performance"
    }
    source_files = {entry["source_file"] for entry in definitions}
    actual: set[str] = set()
    for source_file in source_files:
        actual.update(_performance_nodes_in_source(source_file))

    assert actual == expected
    assert all(_has_performance_marker(_function_node(entry["node_pattern"])) for entry in definitions)


def test_mixed_tests_have_portable_correctness_companions() -> None:
    definitions = _manifest()["definitions"]
    mixed = [entry for entry in definitions if entry["classification"] == "MIXED_CORRECTNESS_PERFORMANCE"]
    assert mixed

    for entry in mixed:
        companion_pattern = entry["correctness_companion"]
        assert companion_pattern, f"missing correctness companion for {entry['node_pattern']}"
        companion = _function_node(companion_pattern)
        assert not _has_performance_marker(companion), companion_pattern


def test_hang_guards_remain_portable_and_performance_marker_is_registered() -> None:
    payload = _manifest()
    for entry in payload["hang_guards"]:
        assert entry["classification"] == "HANG_GUARD"
        assert entry["authority"] == "PORTABLE_BLOCKING"
        assert entry["target_marker"] != "performance"
        assert not _has_performance_marker(_function_node(entry["node_pattern"]))

    parser = configparser.ConfigParser()
    parser.read(ROOT / "pytest.ini", encoding="utf-8")
    markers = parser.get("pytest", "markers")
    assert "performance:" in markers
