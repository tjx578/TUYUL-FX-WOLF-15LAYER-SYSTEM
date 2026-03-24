"""
Journal Writer - Immutable JSON file persistence.

Writes journal entries to storage/decision_archive/{YYYY-MM-DD}/
Format: {timestamp}_{journal_type}_{pair}.json

APPEND-ONLY. No update. No delete.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from loguru import logger

from journal.journal_schema import (
    ContextJournal,
    DecisionJournal,
    ExecutionJournal,
    ReflectiveJournal,
)
from utils.timezone_utils import now_utc


class JournalWriter:
    """
    Immutable JSON file writer for journal entries.
    Organizes files by date under storage/decision_archive/YYYY-MM-DD/
    """

    def __init__(self, base_dir: str = "storage/decision_archive"):
        """
        Initialize JournalWriter.

        Args:
            base_dir: Base directory for journal storage
        """
        self.base_dir = Path(base_dir)

    def write(
        self,
        payload: ContextJournal | DecisionJournal | ExecutionJournal | ReflectiveJournal,
    ) -> Path:
        """
        Write journal entry to disk.

        Args:
            payload: Pydantic model instance (J1-J4)

        Returns:
            Path to written file

        Raises:
            IOError: If file write fails
        """
        # Determine journal type from class name
        journal_type = payload.__class__.__name__.replace("Journal", "").lower()

        # Get current timestamp for filename and metadata
        now = now_utc()
        date_str = now.strftime("%Y-%m-%d")
        timestamp_str = now.strftime("%Y%m%d_%H%M%S_%f")[:-3]  # Include milliseconds

        # Create date-based directory
        date_dir = self.base_dir / date_str
        date_dir.mkdir(parents=True, exist_ok=True)

        # Build filename: {timestamp}_{journal_type}_{pair}.json
        pair = payload.pair
        filename = f"{timestamp_str}_{journal_type}_{pair}.json"
        file_path = date_dir / filename

        # Prepare file content
        file_content = {
            "journal_type": journal_type,
            "recorded_at": now.isoformat(),
            "data": payload.model_dump(mode="json"),
        }

        try:
            # Enforce append-only behavior: create a brand new file only.
            # If a collision occurs, generate a new immutable filename.
            target_path = self._resolve_unique_path(file_path)
            with open(target_path, "x", encoding="utf-8") as f:
                json.dump(file_content, f, indent=2, ensure_ascii=False)

            logger.debug(f"Journal written: {target_path}")
            return target_path

        except Exception as exc:
            logger.error(f"Failed to write journal: {exc}")
            raise OSError(f"Journal write failed: {exc}") from exc

    @staticmethod
    def _resolve_unique_path(file_path: Path) -> Path:
        """Return a non-existing immutable file path derived from the base name."""
        if not file_path.exists():
            return file_path

        stem = file_path.stem
        suffix = file_path.suffix
        while True:
            candidate = file_path.with_name(f"{stem}_{uuid.uuid4().hex[:8]}{suffix}")
            if not candidate.exists():
                return candidate
