"""Acceptance evaluation, CLI and isolation boundary of the offline shadow harness."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.shadow_harness_helpers import (
    POLICY_PATH,
    REPO_ROOT,
    broker_dry_run,
    bundle,
    candidate,
    encode,
    evaluate,
    load_real,
    natural_chain,
    risk_dry_run,
    tradeplan,
)
from tools.shadow_harness.cli import EXIT_GATE_FAILED, EXIT_GATE_PASSED, EXIT_INPUT_REJECTED, main
from tools.shadow_harness.evaluator import evaluate_bundle_bytes
from tools.shadow_harness.manifest import HarnessInputError

ACCEPTANCE_KEYS = {
    "30_PAIR_EVALUATED",
    "OPERATOR_PAIR_SELECTION",
    "OPERATOR_DIRECTION_SELECTION",
    "CROSS_PAIR_CONTAMINATION",
    "BROKER_SUBMIT",
}
NATURAL = ("EURUSD", "GBPJPY", "XAUUSD")


def test_thirty_pair_natural_run_passes_with_wait_for_the_rest() -> None:
    loaded, universe = load_real()
    report = evaluate(
        bundle(loaded, universe, {symbol: natural_chain(symbol, universe) for symbol in NATURAL}), loaded, universe
    )
    acceptance = report.to_json_dict()["acceptance"]
    assert acceptance == {
        "30_PAIR_EVALUATED": True,
        "OPERATOR_PAIR_SELECTION": False,
        "OPERATOR_DIRECTION_SELECTION": False,
        "CROSS_PAIR_CONTAMINATION": 0,
        "BROKER_SUBMIT": 0,
    }
    assert report.gate_passed and report.gate_failures == ()
    statuses = {item.symbol: item.status for item in report.symbols}
    assert len(statuses) == 30
    assert {symbol for symbol, status in statuses.items() if status == "CANDIDATE"} == set(NATURAL)
    assert sum(status == "WAIT" for status in statuses.values()) == 27
    wait = next(item for item in report.symbols if item.status == "WAIT")
    assert (wait.candidate_count, wait.candidate_ids, wait.capture_counts) == (0, (), {})


def test_zero_candidates_is_thirty_wait_and_still_evaluated() -> None:
    loaded, universe = load_real()
    report = evaluate(bundle(loaded, universe), loaded, universe)
    assert report.acceptance.pair_30_evaluated is True
    assert {item.status for item in report.symbols} == {"WAIT"}
    assert report.gate_passed


def test_multiple_natural_candidates_per_symbol_are_counted() -> None:
    loaded, universe = load_real()
    chains = natural_chain("EURUSD", universe, 1) + natural_chain("EURUSD", universe, 2)
    report = evaluate(bundle(loaded, universe, {"EURUSD": chains}), loaded, universe)
    eur = next(item for item in report.symbols if item.symbol == "EURUSD")
    assert eur.candidate_count == 2
    assert eur.capture_counts["TRADEPLAN"] == 2
    assert report.gate_passed


def test_twenty_nine_pairs_is_not_thirty_pair_evaluated() -> None:
    loaded, universe = load_real()
    report = evaluate(bundle(loaded, universe, symbols=universe.symbols[:-1]), loaded, universe)
    assert report.acceptance.pair_30_evaluated is False
    assert report.gate_failures == ("NOT_30_PAIR_EVALUATED",)
    assert report.symbols[-1].status == "NOT_EVALUATED"


def test_duplicate_pair_key_in_bundle_is_rejected() -> None:
    loaded, universe = load_real()
    raw = encode(bundle(loaded, universe)).replace(b'"AUDCAD": []', b'"AUDCAD": [], "AUDCAD": []', 1)
    with pytest.raises(HarnessInputError) as info:
        evaluate_bundle_bytes(raw, loaded, universe)
    assert info.value.code == "DUPLICATE_JSON_KEY"


def test_operator_selected_pair_in_header_fails() -> None:
    loaded, universe = load_real()
    report = evaluate(
        bundle(loaded, universe, header_overrides={"operator_selected_symbols": ["EURUSD"]}), loaded, universe
    )
    assert report.acceptance.operator_pair_selection is True
    assert report.gate_failures == ("OPERATOR_PAIR_SELECTION",)


def test_operator_selected_pair_on_candidate_fails() -> None:
    loaded, universe = load_real()
    chosen = candidate("EURUSD", pair_selection_source="OPERATOR")
    report = evaluate(bundle(loaded, universe, {"EURUSD": [chosen]}), loaded, universe)
    assert report.acceptance.operator_pair_selection is True
    assert not report.gate_passed


def test_operator_direction_selection_fails_from_header_or_tradeplan() -> None:
    loaded, universe = load_real()
    by_header = evaluate(
        bundle(
            loaded,
            universe,
            header_overrides={"operator_direction_overrides": [{"symbol": "EURUSD", "direction": "SELL"}]},
        ),
        loaded,
        universe,
    )
    assert by_header.acceptance.operator_direction_selection is True
    chain = natural_chain("EURUSD", universe)
    chain[2] = tradeplan("EURUSD", direction_selection_source="OPERATOR")
    by_record = evaluate(bundle(loaded, universe, {"EURUSD": chain}), loaded, universe)
    assert by_record.acceptance.operator_direction_selection is True
    assert by_record.acceptance.operator_pair_selection is False
    assert by_record.gate_failures == ("OPERATOR_DIRECTION_SELECTION",)


def test_broker_submit_is_counted_and_fails() -> None:
    loaded, universe = load_real()
    chain = natural_chain("EURUSD", universe)
    chain[3] = broker_dry_run("EURUSD", universe, broker_submit_attempted=True)
    chain[4] = risk_dry_run("EURUSD", broker_submit_attempted=True)
    report = evaluate(bundle(loaded, universe, {"EURUSD": chain}), loaded, universe)
    assert report.acceptance.broker_submit == 2
    assert report.gate_failures == ("BROKER_SUBMIT",)


@pytest.mark.parametrize(
    "field",
    ["policy_sha256", "symbol_universe_sha256", "policy_version"],
)
def test_bundle_bound_to_another_policy_is_rejected(field: str) -> None:
    loaded, universe = load_real()
    wrong = "9.9.9" if field == "policy_version" else "0" * 64
    with pytest.raises(HarnessInputError) as info:
        evaluate(bundle(loaded, universe, header_overrides={field: wrong}), loaded, universe)
    assert info.value.code == "HEADER_BINDING_MISMATCH"


def test_operator_fields_are_required_not_defaulted() -> None:
    loaded, universe = load_real()
    payload = bundle(loaded, universe)
    del payload["header"]["operator_selected_symbols"]
    with pytest.raises(HarnessInputError) as info:
        evaluate(payload, loaded, universe)
    assert info.value.code == "BUNDLE_SCHEMA_INVALID"


def test_report_is_deterministic_and_has_exact_acceptance_keys() -> None:
    loaded, universe = load_real()
    payload = bundle(loaded, universe, {"EURUSD": natural_chain("EURUSD", universe)})
    first = evaluate(payload, loaded, universe).to_json_dict()
    second = evaluate(payload, loaded, universe).to_json_dict()
    assert first == second
    assert set(first["acceptance"]) == ACCEPTANCE_KEYS
    assert first["provenance"]["policy_sha256"] == loaded.policy_sha256


def test_cli_writes_report_and_refuses_overwrite(tmp_path: Path) -> None:
    loaded, universe = load_real()
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_bytes(encode(bundle(loaded, universe, {"EURUSD": natural_chain("EURUSD", universe)})))
    out = tmp_path / "report.json"
    assert main(["--policy", str(POLICY_PATH), "--bundle", str(bundle_path), "--out", str(out)]) == EXIT_GATE_PASSED
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["status"] == "EVALUATED" and report["gate_passed"] is True
    with pytest.raises(SystemExit):
        main(["--policy", str(POLICY_PATH), "--bundle", str(bundle_path), "--out", str(out)])


def test_cli_gate_failure_and_rejection_exit_codes(tmp_path: Path) -> None:
    loaded, universe = load_real()
    failing = tmp_path / "failing.json"
    failing.write_bytes(encode(bundle(loaded, universe, symbols=universe.symbols[:29])))
    out_fail = tmp_path / "fail.json"
    assert main(["--policy", str(POLICY_PATH), "--bundle", str(failing), "--out", str(out_fail)]) == EXIT_GATE_FAILED
    rejected = tmp_path / "rejected.json"
    rejected.write_bytes(b"{not json")
    out_rej = tmp_path / "rejected-report.json"
    code = main(["--policy", str(POLICY_PATH), "--bundle", str(rejected), "--out", str(out_rej)])
    assert code == EXIT_INPUT_REJECTED
    payload = json.loads(out_rej.read_text(encoding="utf-8"))
    assert (payload["status"], payload["rejection_code"], payload["gate_passed"]) == (
        "INPUT_REJECTED",
        "INVALID_JSON",
        False,
    )


PACKAGE_DIR = REPO_ROOT / "tools" / "shadow_harness"
ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "argparse",
    "collections",
    "csv",
    "datetime",
    "decimal",
    "hashlib",
    "io",
    "json",
    "pathlib",
    "typing",
    "pydantic",
    "tools",
}


def test_package_imports_only_stdlib_pydantic_and_itself() -> None:
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                root = name.split(".")[0]
                assert root in ALLOWED_IMPORT_ROOTS, f"{path.name} imports {name}"
                if root == "tools":
                    assert name.startswith("tools.shadow_harness"), f"{path.name} imports {name}"


def test_nothing_outside_the_package_and_its_tests_imports_it() -> None:
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "*.py"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")
    offenders = []
    for name in filter(None, listed.split("\0")):
        path = Path(name)
        if path.parts[:2] == ("tools", "shadow_harness") or (
            path.parts[0] == "tests" and path.name.startswith(("test_shadow_harness_", "shadow_harness_"))
        ):
            continue
        source = (REPO_ROOT / path).read_text(encoding="utf-8", errors="replace")
        if "tools.shadow_harness" in source or "tools/shadow_harness" in source:
            offenders.append(name)
    assert offenders == []


def test_cli_module_runs_as_a_subprocess(tmp_path: Path) -> None:
    loaded, universe = load_real()
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_bytes(encode(bundle(loaded, universe)))
    out = tmp_path / "report.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.shadow_harness.cli",
            "--policy",
            str(POLICY_PATH),
            "--bundle",
            str(bundle_path),
            "--out",
            str(out),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == EXIT_GATE_PASSED
    assert json.loads(out.read_text(encoding="utf-8"))["acceptance"]["30_PAIR_EVALUATED"] is True
