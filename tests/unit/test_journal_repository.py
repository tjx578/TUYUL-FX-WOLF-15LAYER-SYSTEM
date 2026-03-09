from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from journal.journal_repository import JournalRepository
from journal.journal_schema import ContextJournal, DecisionJournal, VerdictType


class _FakePostgres:
    def __init__(self) -> None:  # pyright: ignore[reportMissingSuperCall]
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    @property
    def is_available(self) -> bool:
        return True

    async def execute(self, query: str, *args: object) -> str:
        self.calls.append((query, args))
        return "OK"


def _context(pair: str = "EURUSD") -> ContextJournal:
    return ContextJournal(
        timestamp=datetime.now(UTC),
        pair=pair,
        session="LONDON",
        market_regime="TRENDING",
        news_lock=False,
        context_coherence=0.8,
        mta_alignment=True,
        technical_bias="BULLISH",
    )


def _decision(setup_id: str, pair: str = "EURUSD") -> DecisionJournal:
    return DecisionJournal(
        timestamp=datetime.now(UTC),
        pair=pair,
        setup_id=setup_id,
        wolf_30_score=25,
        f_score=8,
        t_score=8,
        fta_score=8,
        exec_score=8,
        tii_sym=0.9,
        integrity_index=0.9,
        monte_carlo_win=0.6,
        conf12=0.8,
        verdict=VerdictType.EXECUTE_BUY,
        confidence="HIGH",
        wolf_status="PACK",
        gates_passed=9,
    )


def test_append_creates_immutable_files(tmp_path: Path):
    repo = JournalRepository(base_dir=str(tmp_path))

    first_path = repo.append(_context())
    second_path = repo.append(_context())

    assert first_path.exists()
    assert second_path.exists()
    assert first_path != second_path


def test_load_entries_filters_by_type_pair_and_setup(tmp_path: Path):
    repo = JournalRepository(base_dir=str(tmp_path))

    setup_id = "EURUSD_20260309_120000"
    repo.append(_context(pair="EURUSD"))
    repo.append(_context(pair="GBPUSD"))
    repo.append(_decision(setup_id=setup_id, pair="EURUSD"))

    decision_only = repo.load_entries(date_range_days=7, journal_types=["decision"])
    assert len(decision_only) == 1
    assert decision_only[0]["journal_type"] == "decision"

    eurusd_only = repo.load_entries(date_range_days=7, pair="EURUSD")
    assert len(eurusd_only) == 2

    setup_only = repo.load_for_setup(setup_id=setup_id, date_range_days=7)
    assert len(setup_only) == 1
    assert setup_only[0]["data"]["setup_id"] == setup_id


def test_load_entries_returns_empty_for_invalid_range(tmp_path: Path):
    repo = JournalRepository(base_dir=str(tmp_path))
    repo.append(_context())

    assert repo.load_entries(date_range_days=0) == []


def test_append_writes_to_postgres_when_available(tmp_path: Path) -> None:
    fake_pg = _FakePostgres()
    repo = JournalRepository(base_dir=str(tmp_path), pg=fake_pg)  # type: ignore[arg-type]

    setup_id = "EURUSD_20260309_120000"
    path = repo.append(_decision(setup_id=setup_id))

    assert path.exists()
    assert len(fake_pg.calls) == 2

    create_query, _ = fake_pg.calls[0]
    insert_query, insert_args = fake_pg.calls[1]

    assert "CREATE TABLE IF NOT EXISTS journal_entries" in create_query
    assert "INSERT INTO journal_entries" in insert_query

    # journal_type, signal_id, pair, recorded_at, payload, file_path
    assert insert_args[0] == "J2"
    assert insert_args[1] == setup_id
    assert insert_args[2] == "EURUSD"
    assert str(path) == insert_args[5]

    payload = json.loads(str(insert_args[4]))
    assert payload["setup_id"] == setup_id
    assert payload["verdict"] == "EXECUTE_BUY"
