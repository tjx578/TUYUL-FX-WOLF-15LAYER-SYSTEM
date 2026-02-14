"""Regression test: ensure no non-ASCII dashes sneak into Python source files."""

import os
import re

# Characters that have historically caused SyntaxError
NON_ASCII_DASHES = re.compile("[\u2012\u2013\u2014\u2015]")


def _python_files():
    """Yield every .py file in the repository (excluding venv / .git)."""
    skip = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox"}
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in skip]
        for fname in files:
            if fname.endswith(".py"):
                yield os.path.join(root, fname)


def test_no_non_ascii_dashes_in_source():
    """Every .py file must be free of Unicode dash characters that break parsing."""
    violations = []
    for path in _python_files():
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if NON_ASCII_DASHES.search(line):
                    violations.append(f"{path}:{lineno}: {line.rstrip()}")
    assert not violations, (
        "Non-ASCII dash characters found in source files:\n"
        + "\n".join(violations)
    )
