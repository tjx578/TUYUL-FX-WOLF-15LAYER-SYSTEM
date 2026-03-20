"""Regression test: ensure no non-ASCII dashes sneak into Python source code."""

import io
import os
import re
import tokenize

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
    """Executable Python tokens must not contain Unicode dash characters."""
    violations = []
    for path in _python_files():
        with open(path, encoding="utf-8") as fh:
            source = fh.read()

        # Only flag dashes in executable tokens. Comments/docstrings/user-facing
        # text may legitimately contain Unicode punctuation.
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type in {tokenize.COMMENT, tokenize.STRING, tokenize.ENCODING}:
                continue
            if NON_ASCII_DASHES.search(tok.string):
                line = source.splitlines()[tok.start[0] - 1] if tok.start[0] > 0 else ""
                violations.append(f"{path}:{tok.start[0]}: {line.rstrip()}")
    assert not violations, "Non-ASCII dash characters found in source files:\n" + "\n".join(violations)
