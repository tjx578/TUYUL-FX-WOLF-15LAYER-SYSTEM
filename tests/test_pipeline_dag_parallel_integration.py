from __future__ import annotations

import threading
import time
from collections.abc import Callable

import pytest

from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline


def _run_sequential_batches(
    dag_batches: list[list[str]],
    batch_calls: dict[str, Callable[[], dict[str, int | str]]],
) -> dict[str, dict[str, int | str]]:
    """Reference executor used to compare against asyncio batch-parallel runner."""
    output: dict[str, dict[str, int | str]] = {}
    for batch in dag_batches:
        for layer_id in batch:
            if layer_id in batch_calls:
                output[layer_id] = batch_calls[layer_id]()
    return output


def _build_dependency_checked_calls(
    dag_batches: list[list[str]],
    active_layers: list[str],
) -> dict[str, Callable[[], dict[str, int | str]]]:
    dag = WolfConstitutionalPipeline._build_pipeline_dag()  # pyright: ignore[reportPrivateUsage]
    active = set(active_layers)
    dependencies = {
        layer: [dep for dep in dag.dependencies_for(layer) if dep in active]
        for layer in active_layers
    }

    state_done: set[str] = set()
    state_values: dict[str, dict[str, int | str]] = {}
    lock = threading.Lock()

    calls: dict[str, Callable[[], dict[str, int | str]]] = {}

    for layer in active_layers:

        def _make_call(layer_id: str):
            def _call() -> dict[str, int | str]:
                with lock:
                    missing = [dep for dep in dependencies[layer_id] if dep not in state_done]
                    assert not missing, f"dependency violation for {layer_id}: {missing}"
                    dep_total = sum(int(state_values[dep]["value"]) for dep in dependencies[layer_id])

                # Small delay to make overlap likely for same-batch nodes.
                time.sleep(0.01 if layer_id in {"L11", "macro"} else 0.002)
                result = {"layer": layer_id, "value": dep_total + len(layer_id)}

                with lock:
                    state_done.add(layer_id)
                    state_values[layer_id] = result
                return result

            return _call

        calls[layer] = _make_call(layer)

    # Ensure the supplied active layers really appear in DAG batches.
    dag_nodes = {node for batch in dag_batches for node in batch}
    assert set(active_layers).issubset(dag_nodes)
    return calls


def test_l11_and_macro_share_same_dag_batch() -> None:
    dag_batches = WolfConstitutionalPipeline._build_pipeline_dag().execution_batches()  # pyright: ignore[reportPrivateUsage]
    batch_index = {
        layer_id: idx
        for idx, batch in enumerate(dag_batches)
        for layer_id in batch
    }

    assert batch_index["L11"] == batch_index["macro"]


def test_pipeline_batch_parallel_matches_sequential_reference() -> None:
    dag_batches = WolfConstitutionalPipeline._build_pipeline_dag().execution_batches()  # pyright: ignore[reportPrivateUsage]
    active_layers = [
        "L1", "L2", "L3",
        "L4", "L5",
        "L7", "L8", "L9",
        "L11", "macro",
        "L6", "L10",
        "L12", "L13", "L15", "L14",
    ]

    parallel_calls = _build_dependency_checked_calls(dag_batches, active_layers)
    parallel_results = WolfConstitutionalPipeline._run_dag_batch_calls(  # pyright: ignore[reportPrivateUsage]
        dag_batches,
        parallel_calls,
    )

    sequential_calls = _build_dependency_checked_calls(dag_batches, active_layers)
    sequential_results = _run_sequential_batches(dag_batches, sequential_calls)

    assert parallel_results == sequential_results


def test_pipeline_batch_parallel_halts_before_next_batch_on_failure() -> None:
    dag_batches = WolfConstitutionalPipeline._build_pipeline_dag().execution_batches()  # pyright: ignore[reportPrivateUsage]
    executed: list[str] = []

    def _ok(layer_id: str) -> Callable[[], dict[str, str]]:
        def _call() -> dict[str, str]:
            executed.append(layer_id)
            return {"layer": layer_id}

        return _call

    def _boom() -> dict[str, str]:
        executed.append("L4")
        raise ValueError("synthetic L4 failure")

    batch_calls: dict[str, Callable[[], dict[str, str]]] = {
        "L1": _ok("L1"),
        "L2": _ok("L2"),
        "L3": _ok("L3"),
        "L4": _boom,
        # L7 is in a later batch than L4 and must never run once L4 fails.
        "L7": _ok("L7"),
    }

    with pytest.raises(RuntimeError, match="DAG_BATCH_FAILED"):
        WolfConstitutionalPipeline._run_dag_batch_calls(  # pyright: ignore[reportPrivateUsage]
            dag_batches,
            batch_calls,
        )

    assert "L4" in executed
    assert "L7" not in executed
