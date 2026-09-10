from pathlib import Path

import pytest

from scripts.ci.validate_suite_junit import validate


def test_executed_suite_passes(tmp_path: Path):
    path = tmp_path / "tests.xml"
    path.write_text('<testsuites><testsuite tests="1"><testcase name="required"/></testsuite></testsuites>')
    assert validate(path) == 1


@pytest.mark.parametrize(
    "xml",
    [
        "<testsuites/>",
        '<testsuite tests="0"/>',
        "<testsuite><testcase/></testsuite>",
        '<testsuite tests="abc"><testcase/></testsuite>',
        '<testsuite tests="2"><testcase/></testsuite>',
        '<testsuite tests="1" skipped="1"><testcase/></testsuite>',
        '<testsuite tests="1"><testcase><skipped/></testcase></testsuite>',
        '<testsuite tests="1"><testcase><failure/></testcase></testsuite>',
        '<testsuite tests="1"><testcase><error/></testcase></testsuite>',
    ],
)
def test_incomplete_or_failed_evidence_is_rejected(tmp_path: Path, xml):
    path = tmp_path / "tests.xml"
    path.write_text(xml)
    with pytest.raises(ValueError):
        validate(path)
