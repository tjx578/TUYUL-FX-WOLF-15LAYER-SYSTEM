"""
Journal Router - Thread-safe singleton event receiver.

Receives and routes journal events (J1-J4) to JournalWriter.
Pattern: Same as LiveContextBus and ExecutionStateMachine.
"""

from threading import Lock

from loguru import logger

from journal.journal_schema import (
    ContextJournal,
    DecisionJournal,
    ExecutionJournal,
    ReflectiveJournal,
)
from journal.journal_writer import JournalWriter


class JournalRouter:
    """
    Thread-safe singleton router for journal events.
    READ-ONLY OBSERVER. Does NOT influence trading decisions.
    """

    _instance = None
    _lock = Lock()

    def __new__(cls):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        """Initialize router state"""
        self._writer = JournalWriter()
        self._event_count = 0
        self._rw_lock = Lock()

    # ========================
    # EVENT HANDLERS
    # ========================

    def record_context(self, j1: ContextJournal) -> None:
        """
        Record J1 context journal entry.

        Args:
            j1: ContextJournal instance
        """
        with self._rw_lock:
            self._event_count += 1
            try:
                self._writer.write(j1)
                logger.debug(f"J1 recorded: {j1.pair} @ {j1.session}")
            except Exception as exc:
                logger.error(f"J1 write failed: {exc}")
                # Don't propagate - journal failures must not break trading loop

    def record_decision(self, j2: DecisionJournal) -> None:
        """
        Record J2 decision journal entry.

        Args:
            j2: DecisionJournal instance
        """
        with self._rw_lock:
            self._event_count += 1
            try:
                self._writer.write(j2)
                logger.info(
                    f"J2 recorded: {j2.pair} | {j2.verdict.value} | "
                    f"Wolf={j2.wolf_30_score} | Gates={j2.gates_passed}/{j2.gates_total}"
                )
            except Exception as exc:
                logger.error(f"J2 write failed: {exc}")
                # Don't propagate - journal failures must not break trading loop

    def record_execution(self, j3: ExecutionJournal) -> None:
        """
        Record J3 execution journal entry.

        Args:
            j3: ExecutionJournal instance
        """
        with self._rw_lock:
            self._event_count += 1
            try:
                self._writer.write(j3)
                logger.info(
                    f"J3 recorded: {j3.pair} | {j3.direction} @ {j3.entry_price} | "
                    f"RR={j3.rr_ratio:.2f} | Risk={j3.risk_percent:.1f}%"
                )
            except Exception as exc:
                logger.error(f"J3 write failed: {exc}")
                # Don't propagate - journal failures must not break trading loop

    def record_reflection(self, j4: ReflectiveJournal) -> None:
        """
        Record J4 reflective journal entry.

        Args:
            j4: ReflectiveJournal instance
        """
        with self._rw_lock:
            self._event_count += 1
            try:
                self._writer.write(j4)
                logger.info(
                    f"J4 recorded: {j4.pair} | {j4.outcome.value} | "
                    f"Protected={j4.did_system_protect.value} | Discipline={j4.discipline_rating}/10"
                )
            except Exception as exc:
                logger.error(f"J4 write failed: {exc}")
                # Don't propagate - journal failures must not break trading loop

    # ========================
    # METRICS
    # ========================

    def get_event_count(self) -> int:
        """
        Get total number of events recorded.

        Returns:
            Total event count
        """
        with self._rw_lock:
            return self._event_count


# ========================
# MODULE-LEVEL SINGLETON
# ========================

journal_router = JournalRouter()
