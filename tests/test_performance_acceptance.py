from xml.etree import ElementTree as ET

import pytest

from scripts.ci.performance_acceptance import entries, validate_results


def _fixture(tmp_path, names, tag=None):
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", tests=str(len(names)))
    for name in names:
        case = ET.SubElement(suite, "testcase", classname="tests.test_fixture.TestFixture", name=name)
        if tag:
            ET.SubElement(case, tag)
    path = tmp_path / "results.xml"
    ET.ElementTree(root).write(path)
    return path


ROWS = [
    {
        "node_pattern": "tests/test_fixture.py::TestFixture::test_case[*]",
        "instance_count": 2,
        "expected_names": ["test_case[a]", "test_case[b]"],
    }
]


def test_accepts_exact_parametrized_identities(tmp_path):
    path = _fixture(tmp_path, ["test_case[a]", "test_case[b]"])
    assert len(validate_results(path, ROWS)) == 2


def test_rejects_same_count_parameter_substitution(tmp_path):
    with pytest.raises(ValueError):
        validate_results(_fixture(tmp_path, ["test_case[a]", "test_case[unreviewed]"]), ROWS)


@pytest.mark.parametrize(
    "names", [[], ["test_case[a]"], ["test_case[a]", "test_case[a]"], ["test_case[a]", "test_case[b]", "test_other"]]
)
def test_rejects_missing_duplicate_and_extra_identities(tmp_path, names):
    with pytest.raises(ValueError):
        validate_results(_fixture(tmp_path, names), ROWS)


@pytest.mark.parametrize("tag", ["failure", "error", "skipped"])
def test_rejects_nonpassing_cases(tmp_path, tag):
    with pytest.raises(ValueError):
        validate_results(_fixture(tmp_path, ["test_case[a]", "test_case[b]"], tag), ROWS)


def test_reviewed_inventory_is_required_by_actual_ci_step():
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[1]
    manifest = yaml.safe_load((root / "tests/performance_gate_manifest.yaml").read_text())
    assert sum(row["instance_count"] for row in entries(manifest)) == 29
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
    step = next(
        step
        for step in workflow["jobs"]["tests"]["steps"]
        if step.get("name") == "Require uninstrumented latency budgets"
    )
    assert step["run"] == "python scripts/ci/performance_acceptance.py"
    assert not step.get("continue-on-error", False)
    manifest["definitions"].pop()
    with pytest.raises(ValueError):
        entries(manifest)
