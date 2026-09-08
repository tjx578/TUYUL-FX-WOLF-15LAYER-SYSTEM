from pathlib import Path

import pytest

from scripts.ci.run_pair_activity_runtime_acceptance import validate_junit


@pytest.mark.parametrize(
    "body,expected",
    [
        ("", 0),
        ("<testcase name='one' classname='t'><skipped/></testcase>", 1),
        ("<testcase name='one' classname='t'><failure/></testcase>", 1),
        ("<testcase name='one' classname='t'><error/></testcase>", 1),
        ("<testcase name='one' classname='t'/>", 2),
        ("<testcase name='one' classname='t'/><testcase name='one' classname='t'/>", 2),
    ],
)
def test_ci_rejects_missing_skipped_failed_or_duplicated_acceptance(tmp_path: Path, body: str, expected: int):
    path = tmp_path / "junit.xml"
    path.write_text(f"<testsuites><testsuite>{body}</testsuite></testsuites>")
    with pytest.raises(ValueError):
        validate_junit(path, ["t.py::one", "t.py::two"][:expected])


def test_ci_accepts_exact_executed_cases(tmp_path: Path):
    path = tmp_path / "junit.xml"
    path.write_text(
        "<testsuites><testsuite><testcase name='one' classname='t'/><testcase name='two' classname='t'/></testsuite></testsuites>"
    )
    assert validate_junit(path, ["t.py::one", "t.py::two"]) == {"tests": 2, "failures": 0, "errors": 0, "skipped": 0}


def test_ci_rejects_same_count_but_different_test_identity(tmp_path: Path):
    path = tmp_path / "junit.xml"
    path.write_text("<testsuites><testsuite><testcase name='wrong' classname='t'/></testsuite></testsuites>")
    with pytest.raises(ValueError):
        validate_junit(path, ["t.py::required"])
