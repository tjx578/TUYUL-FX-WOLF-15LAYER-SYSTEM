"""
Circuit Breaker - Auto-Halt on Catastrophic Loss

Implements a circuit breaker pattern for trading operations.
Halts trading when loss thresholds are exceeded and auto-recovers
after cooldown period.

States:
- CLOSED: Normal operation, trading allowed
- OPEN: Trading halted due to breach
- HALF_OPEN: Recovery probe, limited trading allowed
"""

import json
import threading
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from loguru import logger

from config_loader import load_risk
from storage.redis_client import RedisClient
from utils.timezone_utils import now_utc
from risk.exceptions import CircuitBreakerOpen


class CircuitBreakerState(Enum):
    """Circuit breaker states."""
    CLOSED = "CLOSED"          # Normal operation
    OPEN = "OPEN"              # Trading halted
    HALF_OPEN = "HALF_OPEN"    # Recovery probe


class CircuitBreaker:
    """
    Auto-halt circuit breaker for catastrophic loss scenarios.
    
    Triggers OPEN state when:
    - Daily loss exceeds threshold (default 3%)
    - Consecutive losses exceed limit (default 3)
    - Drawdown velocity is too fast (>2% in 1 hour)
    
    Auto-recovers after cooldown period (default 4 hours).
    Persists state to Redis for restart survival.
    
    Attributes
    ----------
    daily_loss_threshold : float
        Daily loss % that triggers OPEN (e.g., 0.03 = 3%)
    consecutive_loss_limit : int
        Number of consecutive losses that trigger OPEN
    velocity_threshold : float
        Loss % per hour that triggers OPEN (e.g., 0.02 = 2%)
    cooldown_hours : int
        Hours to wait before auto-reset to HALF_OPEN
    """
    
    def __init__(
        self,
        initial_balance: float,
        daily_loss_threshold: Optional[float] = None,
        consecutive_loss_limit: Optional[int] = None,
        velocity_threshold: Optional[float] = None,
        velocity_window_hours: Optional[int] = None,
        cooldown_hours: Optional[int] = None,
    ):
        """
        Initialize CircuitBreaker.
        
        Parameters
        ----------
        initial_balance : float
            Account balance for loss % calculations
        daily_loss_threshold : float, optional
            Loss % to trigger OPEN (loaded from config if None)
        consecutive_loss_limit : int, optional
            Consecutive losses to trigger OPEN (loaded from config if None)
        velocity_threshold : float, optional
            Loss %/hour to trigger OPEN (loaded from config if None)
        velocity_window_hours : int, optional
            Window for velocity calculation (loaded from config if None)
        cooldown_hours : int, optional
            Hours before auto-reset (loaded from config if None)
        """
        self._lock = threading.Lock()
        self._redis = RedisClient()
        self._config = load_risk()
        
        # Load config
        cb_config = self._config["circuit_breaker"]
        self.daily_loss_threshold = (
            daily_loss_threshold or cb_config["daily_loss_threshold"]
        )
        self.consecutive_loss_limit = (
            consecutive_loss_limit or cb_config["consecutive_loss_limit"]
        )
        self.velocity_threshold = (
            velocity_threshold or cb_config["velocity_threshold"]
        )
        self.velocity_window_hours = (
            velocity_window_hours or cb_config["velocity_window_hours"]
        )
        self.cooldown_hours = (
            cooldown_hours or cb_config["cooldown_hours"]
        )
        self.recovery_probe_trades = cb_config["recovery_probe_trades"]
        
        self._balance = initial_balance
        
        # Redis keys
        keys = self._config["redis_keys"]
        self._key_state = keys["circuit_breaker_state"]
        self._key_data = keys["circuit_breaker_data"]
        self._key_consecutive = keys["consecutive_losses"]
        self._key_history = keys["trade_history"]
        
        # Load or initialize state
        self._load_or_initialize()
        
        logger.info(
            "CircuitBreaker initialized",
            state=self._state.value,
            daily_threshold=self.daily_loss_threshold * 100,
            consecutive_limit=self.consecutive_loss_limit,
            velocity_threshold=self.velocity_threshold * 100,
            cooldown_hours=self.cooldown_hours,
        )
    
    def _load_or_initialize(self) -> None:
        """Load state from Redis or initialize."""
        with self._lock:
            # Load state
            state_str = self._redis.get(self._key_state)
            if state_str:
                self._state = CircuitBreakerState(state_str)
            else:
                self._state = CircuitBreakerState.CLOSED
            
            # Load data (opened_at timestamp, probe count)
            data = self._redis.get(self._key_data)
            if data:
                parts = data.split("|")
                self._opened_at = (
                    datetime.fromisoformat(parts[0]) if parts[0] else None
                )
                self._probe_count = int(parts[1]) if len(parts) > 1 else 0
            else:
                self._opened_at = None
                self._probe_count = 0
            
            # Load consecutive losses
            consecutive = self._redis.get(self._key_consecutive)
            self._consecutive_losses = int(consecutive) if consecutive else 0
            
            # Persist initial state
            if not state_str:
                self._persist_state()
    
    def _persist_state(self) -> None:
        """Persist state to Redis. Must be called within lock."""
        try:
            self._redis.set(self._key_state, self._state.value)
            
            data = f"{self._opened_at.isoformat() if self._opened_at else ''}|{self._probe_count}"
            self._redis.set(self._key_data, data)
            
            self._redis.set(self._key_consecutive, str(self._consecutive_losses))
        except Exception as e:
            logger.error(
                "Failed to persist circuit breaker state",
                error=str(e)
            )
    
    def _check_auto_recovery(self) -> None:
        """Check if cooldown has elapsed and auto-recover to HALF_OPEN."""
        if (
            self._state == CircuitBreakerState.OPEN 
            and self._opened_at
        ):
            now = now_utc()
            elapsed = now - self._opened_at
            
            if elapsed >= timedelta(hours=self.cooldown_hours):
                logger.info(
                    "Circuit breaker cooldown elapsed, moving to HALF_OPEN",
                    elapsed_hours=elapsed.total_seconds() / 3600,
                )
                self._transition_to(CircuitBreakerState.HALF_OPEN)
    
    def _transition_to(self, new_state: CircuitBreakerState) -> None:
        """
        Transition to new state.
        
        Must be called within lock.
        """
        old_state = self._state
        self._state = new_state
        
        if new_state == CircuitBreakerState.OPEN:
            self._opened_at = now_utc()
            self._probe_count = 0
        elif new_state == CircuitBreakerState.HALF_OPEN:
            self._probe_count = 0
        elif new_state == CircuitBreakerState.CLOSED:
            self._opened_at = None
            self._consecutive_losses = 0
            self._probe_count = 0
        
        self._persist_state()
        
        logger.warning(
            "Circuit breaker state transition",
            old_state=old_state.value,
            new_state=new_state.value,
            consecutive_losses=self._consecutive_losses,
        )
    
    def _check_daily_loss(self, daily_loss: float) -> bool:
        """Check if daily loss exceeds threshold."""
        if self._balance <= 0:
            return False
        
        loss_pct = daily_loss / self._balance
        
        if loss_pct >= self.daily_loss_threshold:
            logger.warning(
                "Daily loss threshold breached",
                loss_pct=loss_pct * 100,
                threshold=self.daily_loss_threshold * 100,
            )
            return True
        
        return False
    
    def _check_consecutive_losses(self) -> bool:
        """Check if consecutive losses exceed limit."""
        if self._consecutive_losses >= self.consecutive_loss_limit:
            logger.warning(
                "Consecutive loss limit breached",
                consecutive=self._consecutive_losses,
                limit=self.consecutive_loss_limit,
            )
            return True
        
        return False
    
    def _check_velocity(self) -> bool:
        """Check if drawdown velocity exceeds threshold."""
        # Get recent trades from history
        history_json = self._redis.get(self._key_history)
        if not history_json:
            return False
        
        try:
            trades = json.loads(history_json)
        except json.JSONDecodeError:
            return False
        
        if not trades:
            return False
        
        # Calculate loss in velocity window
        now = now_utc()
        cutoff = now - timedelta(hours=self.velocity_window_hours)
        
        recent_loss = 0.0
        for trade in trades:
            trade_time = datetime.fromisoformat(trade["timestamp"])
            if trade_time >= cutoff and trade["pnl"] < 0:
                recent_loss += abs(trade["pnl"])
        
        if self._balance <= 0:
            return False
        
        velocity_pct = recent_loss / self._balance
        
        if velocity_pct >= self.velocity_threshold:
            logger.warning(
                "Drawdown velocity threshold breached",
                velocity_pct=velocity_pct * 100,
                threshold=self.velocity_threshold * 100,
                window_hours=self.velocity_window_hours,
            )
            return True
        
        return False
    
    def record_trade(
        self, 
        pnl: float, 
        pair: str, 
        daily_loss: float
    ) -> None:
        """
        Record a trade result and check circuit breaker conditions.
        
        Parameters
        ----------
        pnl : float
            Trade profit/loss
        pair : str
            Trading pair
        daily_loss : float
            Total daily loss so far (for daily threshold check)
        """
        with self._lock:
            # Check for auto-recovery first
            self._check_auto_recovery()
            
            # Record trade in history
            history_json = self._redis.get(self._key_history) or "[]"
            try:
                trades = json.loads(history_json)
            except json.JSONDecodeError:
                trades = []
            
            trades.append({
                "timestamp": now_utc().isoformat(),
                "pair": pair,
                "pnl": pnl,
            })
            
            # Keep only last 100 trades
            trades = trades[-100:]
            self._redis.set(self._key_history, json.dumps(trades))
            
            # Update consecutive losses
            if pnl < 0:
                self._consecutive_losses += 1
            else:
                self._consecutive_losses = 0
            
            # In HALF_OPEN, track probe trades
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._probe_count += 1
                
                if pnl < 0:
                    # Failed recovery, back to OPEN
                    logger.warning(
                        "Recovery probe failed, returning to OPEN",
                        pnl=pnl
                    )
                    self._transition_to(CircuitBreakerState.OPEN)
                    return
                
                if self._probe_count >= self.recovery_probe_trades:
                    # Successful recovery
                    logger.info(
                        "Recovery probe successful, moving to CLOSED",
                        probe_count=self._probe_count
                    )
                    self._transition_to(CircuitBreakerState.CLOSED)
                    return
            
            # Check breach conditions (only in CLOSED state)
            if self._state == CircuitBreakerState.CLOSED:
                breached = (
                    self._check_daily_loss(daily_loss) or
                    self._check_consecutive_losses() or
                    self._check_velocity()
                )
                
                if breached:
                    self._transition_to(CircuitBreakerState.OPEN)
            
            self._persist_state()
    
    def is_trading_allowed(self) -> bool:
        """
        Check if trading is allowed based on circuit breaker state.
        
        Returns
        -------
        bool
            True if trading allowed (CLOSED or HALF_OPEN)
        """
        with self._lock:
            # Check for auto-recovery
            self._check_auto_recovery()
            
            allowed = self._state in [
                CircuitBreakerState.CLOSED,
                CircuitBreakerState.HALF_OPEN,
            ]
            
            return allowed
    
    def get_state(self) -> str:
        """Get current circuit breaker state."""
        with self._lock:
            self._check_auto_recovery()
            return self._state.value
    
    def get_snapshot(self) -> dict:
        """
        Get circuit breaker snapshot.
        
        Returns
        -------
        dict
            Current state, consecutive losses, and timestamps
        """
        with self._lock:
            self._check_auto_recovery()
            
            return {
                "state": self._state.value,
                "trading_allowed": self.is_trading_allowed(),
                "consecutive_losses": self._consecutive_losses,
                "opened_at": (
                    self._opened_at.isoformat() if self._opened_at else None
                ),
                "probe_count": self._probe_count,
                "thresholds": {
                    "daily_loss_pct": self.daily_loss_threshold * 100,
                    "consecutive_limit": self.consecutive_loss_limit,
                    "velocity_pct_per_hour": self.velocity_threshold * 100,
                },
            }
    
    def check_and_raise(self) -> None:
        """
        Check state and raise exception if trading not allowed.
        
        Raises
        ------
        CircuitBreakerOpen
            If circuit breaker is OPEN
        """
        if not self.is_trading_allowed():
            snapshot = self.get_snapshot()
            raise CircuitBreakerOpen(
                f"Circuit breaker is {snapshot['state']}: "
                f"consecutive_losses={snapshot['consecutive_losses']}"
            )
