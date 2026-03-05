from core.dag_engine import DagCycleError, DagEngine


def test_topological_sort_and_batches() -> None:
    dag = DagEngine()
    dag.add_edge("L1", "L4")
    dag.add_edge("L2", "L4")
    dag.add_edge("L3", "L4")
    dag.add_edge("L4", "L7")

    order = dag.topological_sort()
    assert order.index("L1") < order.index("L4")
    assert order.index("L2") < order.index("L4")
    assert order.index("L3") < order.index("L4")
    assert order.index("L4") < order.index("L7")

    batches = dag.execution_batches()
    assert batches[0] == ["L1", "L2", "L3"]
    assert batches[1] == ["L4"]
    assert batches[2] == ["L7"]


def test_cycle_raises_error() -> None:
    dag = DagEngine()
    dag.add_edge("A", "B")
    dag.add_edge("B", "C")
    dag.add_edge("C", "A")

    try:
        dag.topological_sort()
    except DagCycleError:
        pass
    else:
        raise AssertionError("expected DagCycleError for cyclic graph")
