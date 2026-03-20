"""In-memory account repository for account-scoped governance state.

This repository is intentionally account-centric and contains no market/signal
decision logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock


@dataclass(frozen=True)
class EAInstanceConfig:
	"""Per-account EA instance configuration (isolation boundary)."""

	ea_instance_id: str
	strategy_profile: str
	risk_multiplier: float = 1.0
	news_lock_setting: str = "DEFAULT"
	enabled: bool = True


@dataclass(frozen=True)
class AccountRiskState:
	"""Per-account runtime state used by risk firewall and calculators."""

	account_id: str
	prop_firm_code: str
	balance: float
	equity: float
	base_risk_percent: float
	max_daily_loss_percent: float
	max_total_loss_percent: float
	daily_loss_used_percent: float = 0.0
	total_loss_used_percent: float = 0.0
	consistency_limit_percent: float = 0.0
	consistency_used_percent: float = 0.0
	min_safe_risk_percent: float = 0.2
	account_locked: bool = False
	phase_mode: str = "FUNDED"
	pair_cooldown: dict[str, str] = field(default_factory=dict)
	max_concurrent_trades: int = 5
	open_trades_count: int = 0
	news_lock: bool = False
	correlation_bucket: str = "GREEN"
	compliance_mode: bool = True
	circuit_breaker_open: bool = False
	system_state: str = "NORMAL"
	lockdown_reason: str = ""
	ea_connected: bool = True
	abnormal_slippage: bool = False
	daily_dd_block_threshold_percent: float = 95.0
	total_dd_block_threshold_percent: float = 95.0
	ea_instances: tuple[EAInstanceConfig, ...] = field(default_factory=tuple)

	def in_pair_cooldown(self, symbol: str, now: datetime | None = None) -> bool:
		"""Return True when `symbol` is still in cooldown for this account."""
		now_dt = now or datetime.now(timezone.utc)
		raw = self.pair_cooldown.get(symbol.upper())
		if not raw:
			return False
		try:
			until = datetime.fromisoformat(raw.replace("Z", "+00:00"))
		except ValueError:
			return False
		return until > now_dt


class AccountRepository:
	"""Thread-safe in-memory account state repository."""

	_instances: dict[str, "AccountRepository"] = {}
	_instances_lock = Lock()

	def __init__(self) -> None:
		self._lock = Lock()
		self._state_by_account: dict[str, AccountRiskState] = {}

	@classmethod
	def get_default(cls) -> "AccountRepository":
		"""Get singleton repository instance."""
		with cls._instances_lock:
			if "default" not in cls._instances:
				cls._instances["default"] = cls()
			return cls._instances["default"]

	def upsert_state(self, state: AccountRiskState) -> AccountRiskState:
		"""Create or update account risk state."""
		with self._lock:
			self._state_by_account[state.account_id] = state
			return state

	def get_state(self, account_id: str) -> AccountRiskState | None:
		"""Read account risk state by explicit `account_id`."""
		with self._lock:
			return self._state_by_account.get(account_id)

	def list_states(self) -> list[AccountRiskState]:
		"""Return all account states."""
		with self._lock:
			return list(self._state_by_account.values())

