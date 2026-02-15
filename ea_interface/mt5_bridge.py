"""
MT5 Bridge — dumb execution relay.
Receives execution commands from dashboard (after L12 verdict + risk check).
Places orders on MT5. Reports back.
ZERO intelligence. ZERO market analysis. ZERO overrides.
"""

from __future__ import annotations

import json
import logging
import time

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger("tuyul.ea.mt5_bridge")


class BridgeMode(Enum):
    """How the bridge communicates with MT5."""
    FILE_BASED = "FILE_BASED"    # Write JSON files that EA polls (safest, most compatible)
    SOCKET = "SOCKET"             # TCP/Named pipe (lower latency, more complex)
    # MT5_PYTHON = "MT5_PYTHON"   # Direct MetaTrader5 Python lib (Windows only)


@dataclass
class ExecutionCommand:
    """Command sent TO the EA. Dashboard authority, not analysis."""
    signal_id: str
    symbol: str
    direction: str          # "BUY" or "SELL"
    order_type: str         # "LIMIT", "STOP", "MARKET"
    entry_price: float
    stop_loss: float
    take_profit: float
    lot_size: float         # FROM dashboard risk calculator, NOT from analysis
    magic_number: int = 151515
    comment: str = "TUYUL-FX"
    expiry_seconds: float = 300.0
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class ExecutionReport:
    """Report FROM the EA back to dashboard."""
    signal_id: str
    event: str  # ORDER_PLACED, ORDER_FILLED, ORDER_CANCELLED, ORDER_EXPIRED, ORDER_FAILED
    broker_ticket: int | None = None
    fill_price: float | None = None
    slippage_pips: float | None = None
    error_message: str | None = None
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


class FileBasedMT5Bridge:
    """
    File-based bridge for MT5 EA communication.

    Protocol:
    1. Python writes command JSON to `commands/` directory
    2. MT5 EA polls `commands/`, reads, executes, deletes
    3. MT5 EA writes result JSON to `reports/` directory
    4. Python polls `reports/`, reads, processes, archives

    This is the SAFEST approach — works on all MT5 setups,
    no DLL imports needed in EA, no network config.
    """

    def __init__(self, bridge_dir: str | Path):
        self._bridge_dir = Path(bridge_dir)
        self._commands_dir = self._bridge_dir / "commands"
        self._reports_dir = self._bridge_dir / "reports"
        self._archive_dir = self._bridge_dir / "archive"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        for d in [self._commands_dir, self._reports_dir, self._archive_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def send_command(self, command: ExecutionCommand) -> bool:
        """
        Write execution command as JSON file for EA to pick up.
        Returns True if file was written successfully.
        """
        filename = f"{command.signal_id}_{int(command.timestamp)}.json"
        filepath = self._commands_dir / filename

        try:
            payload = asdict(command)
            filepath.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            logger.info(
                f"Command sent: {command.signal_id} | "
                f"{command.symbol} {command.direction} {command.order_type} | "
                f"lot={command.lot_size} entry={command.entry_price}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to write command {command.signal_id}: {e}")
            return False

    def poll_reports(self) -> list[ExecutionReport]:
        """
        Read all pending execution reports from EA.
        Archives processed report files.
        """
        reports: list[ExecutionReport] = []

        for filepath in self._reports_dir.glob("*.json"):
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
                report = ExecutionReport(
                    signal_id=data.get("signal_id", "UNKNOWN"),
                    event=data.get("event", "UNKNOWN"),
                    broker_ticket=data.get("broker_ticket"),
                    fill_price=data.get("fill_price"),
                    slippage_pips=data.get("slippage_pips"),
                    error_message=data.get("error_message"),
                    timestamp=data.get("timestamp", time.time()),
                )
                reports.append(report)

                # Archive
                archive_path = self._archive_dir / filepath.name
                filepath.rename(archive_path)

                logger.info(
                    f"Report received: {report.signal_id} | "
                    f"event={report.event} | ticket={report.broker_ticket}"
                )
            except Exception as e:
                logger.error(f"Failed to parse report {filepath}: {e}")

        return reports

    def get_pending_commands(self) -> list[str]:
        """List signal IDs of commands not yet picked up by EA."""
        return [
            f.stem.split("_")[0]
            for f in self._commands_dir.glob("*.json")
        ]

    def cancel_command(self, signal_id: str) -> bool:
        """Remove a pending command before EA picks it up."""
        for filepath in self._commands_dir.glob(f"{signal_id}_*.json"):
            try:
                filepath.unlink()
                logger.info(f"Command cancelled: {signal_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to cancel command {signal_id}: {e}")
        return False

    def health_check(self) -> dict:
        """Check bridge directory health."""
        return {
            "bridge_dir_exists": self._bridge_dir.exists(),
            "commands_dir_exists": self._commands_dir.exists(),
            "reports_dir_exists": self._reports_dir.exists(),
            "pending_commands": len(list(self._commands_dir.glob("*.json"))),
            "unprocessed_reports": len(list(self._reports_dir.glob("*.json"))),
            "archived_reports": len(list(self._archive_dir.glob("*.json"))),
        }
