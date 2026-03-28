"""Tests for SVC-BUG-08: degraded-hold timeout across services.

Validates that all degraded-hold patterns have a finite timeout
so crashed services auto-exit instead of blocking forever.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from unittest.mock import patch

import pytest

import services.engine.runner as engine_runner
import services.ingest.ingest_worker as ingest_worker
import services.orchestrator.state_manager as state_manager


def _has_wait_with_timeout(source_path: str, func_or_scope: str) -> bool:
    """Check via AST that every .wait() call inside the scope has a timeout.

    Handles both:
      - shutdown.wait(timeout=N)
      - asyncio.wait_for(shutdown.wait(), timeout=N)
    """
    tree = ast.parse(Path(source_path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        is_target = (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == func_or_scope
        )
        if not is_target:
            continue

        # Collect all .wait() calls that are wrapped by wait_for()
        wait_for_inner_ids: set[int] = set()
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            # Detect asyncio.wait_for(x.wait(), timeout=...)
            func = child.func
            is_wait_for = (
                (isinstance(func, ast.Attribute) and func.attr == "wait_for")
                or (isinstance(func, ast.Name) and func.id == "wait_for")
            )
            if is_wait_for and child.args:
                # The first arg to wait_for is the awaitable — mark its id
                wait_for_inner_ids.add(id(child.args[0]))

        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            if isinstance(child.func, ast.Attribute) and child.func.attr == "wait":
                # Skip if this wait() is inside a wait_for()
                if id(child) in wait_for_inner_ids:
                    continue
                has_timeout = any(kw.arg == "timeout" for kw in child.keywords)
                if not has_timeout:
                    return False
        return True
    return False


class TestDegradedHoldHasTimeout:
    """Boundary tests: every degraded-hold wait must have a finite timeout."""

    def test_engine_runner_hold_alive_has_timeout(self):
        assert _has_wait_with_timeout(
            engine_runner.__file__, "_hold_alive_for_diagnostics"
        ), "shutdown.wait() in engine runner must have timeout="

    def test_orchestrator_state_manager_run_has_timeout(self):
        assert _has_wait_with_timeout(
            state_manager.__file__, "run"
        ), "shutdown.wait() in orchestrator state_manager.run() must have timeout="

    def test_ingest_worker_bootstrap_has_timeout(self):
        assert _has_wait_with_timeout(
            ingest_worker.__file__, "_bootstrap_and_run"
        ), "shutdown.wait() in ingest_worker must have timeout="


class TestEngineHoldAliveTimeout:
    @pytest.mark.slow
    def test_hold_exits_after_timeout(self):
        """_hold_alive_for_diagnostics returns after DEGRADED_HOLD_TIMEOUT_SEC."""
        with patch.dict(os.environ, {"DEGRADED_HOLD_TIMEOUT_SEC": "1"}):
            # Patch signal.signal to no-op (can't set handlers outside main thread)
            with patch("services.engine.runner._hold_alive_for_diagnostics.__module__"):
                pass
            import signal as _sig

            with patch.object(_sig, "signal"):
                engine_runner._hold_alive_for_diagnostics()
            # If we get here, the timeout worked (didn't block forever)
