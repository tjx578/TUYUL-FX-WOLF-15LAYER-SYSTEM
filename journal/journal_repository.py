"""Journal repository for append-only persistence and read/query operations.

This module preserves constitutional boundaries:
- Write path is append-only through ``JournalWriter`` + optional PostgreSQL append
- No update/delete APIs are exposed
- Repository has no decision or execution authority
"""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

from loguru import logger

from journal.journal_schema import (
    ContextJournal,
    DecisionJournal,
    ExecutionJournal,
    ReflectiveJournal,
)
from journal.journal_writer import JournalWriter
from storage.postgres_client import PostgresClient, pg_client
from utils.timezone_utils import now_utc

JournalPayload = ContextJournal | DecisionJournal | ExecutionJournal | ReflectiveJournal


class JournalRepository:
    """Append-only journal repository with simple read/query capabilities."""

    _TYPE_TO_STAGE: dict[str, str] = {
        "context": "J1",
        "decision": "J2",
        "execution": "J3",
        "reflective": "J4",
    }

    def __init__(
        self,
        base_dir: str = "storage/decision_archive",
        pg: PostgresClient | None = None,
    ) -> None:
        super().__init__()
        self._base_dir = Path(base_dir)
        self._writer = JournalWriter(base_dir=base_dir)
        self._pg = pg if pg is not None else pg_client
        self._table_ready = False

    @property
    def base_dir(self) -> Path:
        """Return configured archive root path."""
        return self._base_dir

    def append(self, payload: JournalPayload) -> Path:
        """Persist a new immutable journal entry and return created file path.

        File persistence is mandatory. PostgreSQL persistence is best-effort and
        must never break the trading/journal loop if unavailable.
        """
        file_path = self._writer.write(payload)
        self._dispatch_db_persist(payload=payload, file_path=file_path)
        return file_path

    async def append_to_db(self, payload: JournalPayload, file_path: Path | None = None) -> bool:
        """Persist one journal entry to PostgreSQL append-only table.

        Returns:
            True when insert is attempted successfully, otherwise False.
        """
        if not self._pg.is_available:
            return False

        try:
            await self._ensure_table()
            await self._pg.execute(
                """INSERT INTO journal_entries
                   (journal_type, signal_id, pair, recorded_at, payload, file_path)
                   VALUES ($1, $2, $3, $4, $5::jsonb, $6)""",
                self._stage_from_payload(payload),
                self._signal_id_from_payload(payload),
                payload.pair,
                payload.timestamp,
                json.dumps(payload.model_dump(mode="json")),
                str(file_path) if file_path else None,
            )
            return True
        except Exception as exc:
            logger.warning(f"Journal PostgreSQL append failed: {exc}")
            return False

    def load_entries(
        self,
        date_range_days: int = 7,
        journal_types: list[str] | None = None,
        pair: str | None = None,
        setup_id: str | None = None,
        limit: int | None = None,
        newest_first: bool = False,
    ) -> list[dict[str, Any]]:
        """Load journal entries from archive with optional filters.

        Args:
            date_range_days: Number of days to look back (inclusive)
            journal_types: Journal type filter (e.g. ["decision", "execution"])
            pair: Pair symbol filter (e.g. "EURUSD")
            setup_id: Setup identifier filter
            limit: Optional max number of entries to return
            newest_first: Whether to sort results descending by ``recorded_at``

        Returns:
            List of parsed JSON entries
        """
        if date_range_days <= 0:
            return []

        if not self._base_dir.exists():
            return []

        entries: list[dict[str, Any]] = []
        end_date = now_utc()
        start_date = end_date - timedelta(days=date_range_days)

        normalized_types = {t.lower() for t in journal_types} if journal_types else None
        normalized_pair = pair.upper() if pair else None

        for date_dir in sorted(self._base_dir.iterdir()):
            if not date_dir.is_dir():
                continue

            dir_date = self._parse_archive_date(date_dir.name, tzinfo=end_date.tzinfo)
            if dir_date is None:
                continue

            if dir_date < start_date or dir_date > end_date:
                continue

            for json_file in date_dir.glob("*.json"):
                entry = self._load_entry_from_file(json_file)
                if entry is None:
                    continue

                if normalized_types and str(entry.get("journal_type", "")).lower() not in normalized_types:
                    continue

                data = entry.get("data", {})
                if normalized_pair and str(data.get("pair", "")).upper() != normalized_pair:
                    continue

                if setup_id and str(data.get("setup_id", "")) != setup_id:
                    continue

                entries.append(entry)

        entries.sort(key=lambda e: str(e.get("recorded_at", "")), reverse=newest_first)
        if limit and limit > 0:
            entries = entries[:limit]
        return [deepcopy(item) for item in entries]

    def _dispatch_db_persist(self, payload: JournalPayload, file_path: Path) -> None:
        """Persist to PostgreSQL without blocking the caller's execution path."""
        if not self._pg.is_available:
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No active event loop (sync context): run one-shot persistence now.
            try:
                asyncio.run(self.append_to_db(payload=payload, file_path=file_path))
            except Exception as exc:
                logger.warning(f"Journal PostgreSQL sync fallback failed: {exc}")
            return

        task = loop.create_task(self.append_to_db(payload=payload, file_path=file_path))
        task.add_done_callback(self._on_db_task_done)

    def _on_db_task_done(self, task: asyncio.Task[bool]) -> None:
        """Consume background task exceptions to avoid event-loop warnings."""
        try:
            _ = task.result()
        except Exception as exc:
            logger.warning(f"Journal PostgreSQL background task failed: {exc}")

    async def _ensure_table(self) -> None:
        """Ensure append-only journal table exists before inserting rows."""
        if self._table_ready:
            return

        await self._pg.execute(
            """CREATE TABLE IF NOT EXISTS journal_entries (
                   id           SERIAL PRIMARY KEY,
                   journal_type VARCHAR(4) NOT NULL,
                   signal_id    VARCHAR(64),
                   pair         VARCHAR(20) NOT NULL,
                   recorded_at  TIMESTAMPTZ NOT NULL,
                   payload      JSONB NOT NULL,
                   file_path    TEXT
               )"""
        )
        self._table_ready = True

    def load_for_setup(self, setup_id: str, date_range_days: int = 30) -> list[dict[str, Any]]:
        """Load all journal entries for a specific setup_id."""
        return self.load_entries(date_range_days=date_range_days, setup_id=setup_id)

    @staticmethod
    def _parse_archive_date(folder_name: str, tzinfo: Any) -> datetime | None:
        """Parse ``YYYY-MM-DD`` archive folder name into timezone-aware datetime."""
        try:
            parsed = datetime.strptime(folder_name, "%Y-%m-%d")
            return parsed.replace(tzinfo=tzinfo)
        except ValueError:
            return None

    @staticmethod
    def _load_entry_from_file(file_path: Path) -> dict[str, Any] | None:
        """Read and parse one journal file, ignoring malformed files."""
        try:
            with open(file_path, encoding="utf-8") as handle:
                raw = json.load(handle)
            if not isinstance(raw, dict):
                return None
            return cast(dict[str, Any], raw)
        except Exception as exc:
            logger.warning(f"Failed to load journal file {file_path}: {exc}")
            return None

    @classmethod
    def _stage_from_payload(cls, payload: JournalPayload) -> str:
        """Map payload model type to immutable journal stage code (J1..J4)."""
        journal_type = payload.__class__.__name__.replace("Journal", "").lower()
        return cls._TYPE_TO_STAGE.get(journal_type, "J0")

    @staticmethod
    def _signal_id_from_payload(payload: JournalPayload) -> str | None:
        """Extract signal/setup identifier from payload when available."""
        raw = payload.model_dump(mode="json")
        candidate = raw.get("signal_id") or raw.get("setup_id")
        if candidate is None:
            return None
        text = str(candidate)
        return text[:64] if text else None
