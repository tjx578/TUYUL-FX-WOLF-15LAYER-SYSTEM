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


def _non_ascii_dash_violations(path, source):
    """Return executable-token violations while skipping impossible inputs."""
    if not NON_ASCII_DASHES.search(source):
        return []

    violations = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type in {tokenize.COMMENT, tokenize.STRING, tokenize.ENCODING}:
            continue
        if NON_ASCII_DASHES.search(tok.string):
            line = source.splitlines()[tok.start[0] - 1] if tok.start[0] > 0 else ""
            violations.append(f"{path}:{tok.start[0]}: {line.rstrip()}")
    return violations


def test_no_non_ascii_dashes_in_source():
    """Executable Python tokens must not contain Unicode dash characters."""
    violations = []
    for path in _python_files():
        with open(path, encoding="utf-8") as fh:
            source = fh.read()

        violations.extend(_non_ascii_dash_violations(path, source))
    violations.sort()
    assert not violations, "Non-ASCII dash characters found in source files:\n" + "\n".join(violations)


def test_ascii_hyphen_minus_is_legal_and_skips_tokenizer(monkeypatch):
    """The legal ASCII hyphen fast path must not invoke the tokenizer."""

    def unexpected_tokenizer(_readline):
        raise AssertionError("clean source must skip tokenization")

    monkeypatch.setattr(tokenize, "generate_tokens", unexpected_tokenizer)

    assert _non_ascii_dash_violations("fixture.py", "result = left - right\n") == []


def test_each_forbidden_dash_in_executable_token_is_detected():
    """Every character in the shared deny-list remains an executable violation."""
    for dash in "\u2012\u2013\u2014\u2015":
        source = f"result = left{dash}right\n"
        assert _non_ascii_dash_violations("fixture.py", source) == [f"fixture.py:1: result = left{dash}right"]


def test_forbidden_dashes_in_non_executable_tokens_are_legal():
    """Comments, strings, and docstrings preserve the established policy."""
    source = "# comment \u2012\nmessage = '\u2013'\n'''docstring \u2014 \u2015'''\n"

    assert _non_ascii_dash_violations("fixture.py", source) == []


def test_raw_dash_candidate_uses_tokenizer(monkeypatch):
    """A raw candidate must still take the semantic tokenizer slow path."""
    original_generate_tokens = tokenize.generate_tokens
    calls = 0

    def tracking_tokenizer(readline):
        nonlocal calls
        calls += 1
        return original_generate_tokens(readline)

    monkeypatch.setattr(tokenize, "generate_tokens", tracking_tokenizer)

    assert _non_ascii_dash_violations("fixture.py", "# candidate \u2014\n") == []
    assert calls == 1
