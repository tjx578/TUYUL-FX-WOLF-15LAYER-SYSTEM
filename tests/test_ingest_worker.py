"""Tests for services/ingest/ingest_worker.py (SVC-BUG-07).

Validates that ingest_service is imported in the main event-loop thread,
not in a thread-pool executor which risks import-lock deadlocks and
async resource creation on the wrong thread.
"""

from __future__ import annotations

import ast
import textwrap

import pytest


def _parse_bootstrap_function() -> ast.AsyncFunctionDef:
    """Parse the _bootstrap_and_run function from ingest_worker.py."""
    import services.ingest.ingest_worker as mod

    source = textwrap.dedent(open(mod.__file__, encoding="utf-8").read())  # noqa: SIM115
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_bootstrap_and_run":
            return node
    pytest.fail("_bootstrap_and_run not found in ingest_worker.py")


class TestIngestWorkerImportSafety:
    def test_no_run_in_executor_for_import(self):
        """ingest_service must NOT be imported via run_in_executor."""
        func = _parse_bootstrap_function()
        for node in ast.walk(func):
            if isinstance(node, ast.Attribute) and node.attr == "run_in_executor":
                pytest.fail(
                    "run_in_executor found in _bootstrap_and_run — "
                    "ingest_service must be imported in the main thread "
                    "to avoid import-lock deadlocks and wrong-thread "
                    "async resource creation"
                )

    def test_no_importlib_import_module(self):
        """importlib.import_module should not be used for ingest_service."""
        func = _parse_bootstrap_function()
        for node in ast.walk(func):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "import_module"
            ):
                pytest.fail(
                    "importlib.import_module found in _bootstrap_and_run — "
                    "use a direct `import ingest_service` statement instead"
                )

    def test_ingest_service_imported_directly(self):
        """Verify ingest_service is imported with a direct import statement."""
        func = _parse_bootstrap_function()
        found = False
        for node in ast.walk(func):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "ingest_service":
                        found = True
        assert found, (
            "Expected `import ingest_service` in _bootstrap_and_run — "
            "direct import keeps it on the main event-loop thread"
        )
