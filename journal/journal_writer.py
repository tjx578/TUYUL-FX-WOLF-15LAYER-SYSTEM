"""
Journal Writer — Immutable JSON file persistence.

Writes journal entries to storage/decision_archive/{YYYY-MM-DD}/
Format: {timestamp}_{journal_type}_{pair}.json

APPEND-ONLY. No update. No delete.
"""

import json
from pathlib import Path
from typing import Union

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
        payload: Union[ContextJournal, DecisionJournal, ExecutionJournal, ReflectiveJournal],
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
        
        # Write to file (atomic write with temp file)
        temp_path = file_path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(file_content, f, indent=2, ensure_ascii=False)
            
            # Atomic rename
            temp_path.rename(file_path)
            
            logger.debug(f"Journal written: {file_path}")
            return file_path
            
        except Exception as exc:
            # Clean up temp file if it exists
            if temp_path.exists():
                temp_path.unlink()
            
            logger.error(f"Failed to write journal: {exc}")
            raise IOError(f"Journal write failed: {exc}") from exc
