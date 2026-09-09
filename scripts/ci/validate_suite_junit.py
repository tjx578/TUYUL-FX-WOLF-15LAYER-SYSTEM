"""Reject empty, skipped or failed required-suite JUnit evidence."""

import sys
from pathlib import Path
from xml.etree import ElementTree as ET


def validate(path: Path) -> int:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    if not suites:
        raise ValueError("MISSING_TEST_SUITE")
    total = 0
    for suite in suites:
        cases = suite.findall("testcase")
        if not cases or int(suite.attrib["tests"]) != len(cases):
            raise ValueError("EMPTY_OR_INCONSISTENT_TEST_SUITE")
        if any(int(suite.get(key, "0")) != 0 for key in ("failures", "errors", "skipped")):
            raise ValueError("REQUIRED_TESTS_NOT_PASSED")
        if any(case.find(tag) is not None for case in cases for tag in ("failure", "error", "skipped")):
            raise ValueError("REQUIRED_TEST_CASE_NOT_PASSED")
        total += len(cases)
    return total


if __name__ == "__main__":
    print(f"Required test cases executed without skip: {validate(Path(sys.argv[1]))}")
