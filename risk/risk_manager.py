"""
Risk Manager - Unified Risk Management Facade

Singleton facade that combines all risk management components:
- DrawdownMonitor (Redis-persistent drawdown tracking)
- CircuitBreaker (auto-halt on catastrophic loss)
- PositionSizer (fixed-fractional position sizing)
- RiskMultiplier (adaptive risk scaling)
- PropFirmRules (prop firm compliance)

Provides simple interface for the rest of the system.
"""

import threading
from typing import Optional

from loguru import logger

from config_loader import load_risk
from risk.drawdown import DrawdownMonitor
from risk.circuit_breaker import CircuitBreaker
from risk.position_sizer import PositionSizer
from risk.risk_multiplier import RiskMultiplier
from risk.prop_firm import PropFirmRules
from risk.exceptions import (
    RiskException,
    CircuitBreakerOpen,
    DrawdownLimitExceeded,
)


class RiskManager:
    """
    Unified risk management facade (Singleton).
    
    Combines all risk components and provides a simple interface:
    - get_risk_snapshot() -> dict (for synthesis integration)
    - record_trade_result() (update drawdown/circuit breaker)
    - calculate_position() (position sizing with risk multiplier)
    - is_trading_allowed() (gate checks)
    
    This is the single entry point for all risk operations.
    
    Usage
    -----
    >>> rm = RiskManager.get_instance(initial_balance=10000)
    >>> snapshot = rm.get_risk_snapshot()
    >>> allowed = rm.is_trading_allowed()
    >>> position = rm.calculate_position(1.0950, 1.0900, "EURUSD")
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __init__(self, initial_balance: float):
        """
        Initialize RiskManager (use get_instance() instead).
        
        Parameters
        ----------
        initial_balance : float
            Starting account balance
        """
        if RiskManager._instance is not None:
            raise RuntimeError(
                "RiskManager is a singleton. Use get_instance()."
            )
        
        self._config = load_risk()
        self._balance = initial_balance
        
        # Initialize components
        self._drawdown = DrawdownMonitor(initial_balance)
        self._circuit_breaker = CircuitBreaker(initial_balance)
        self._position_sizer = PositionSizer()
        self._risk_multiplier = RiskMultiplier()
        self._prop_firm = PropFirmRules()
        
        logger.info(
            "RiskManager initialized",
            initial_balance=initial_balance,
        )
    
    @classmethod
    def get_instance(cls, initial_balance: Optional[float] = None):
        """
        Get RiskManager singleton instance.
        
        Parameters
        ----------
        initial_balance : float, optional
            Required on first call, ignored afterward
            
        Returns
        -------
        RiskManager
            Singleton instance
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    if initial_balance is None:
                        raise ValueError(
                            "initial_balance required for first "
                            "RiskManager initialization"
                        )
                    cls._instance = cls(initial_balance)
        
        return cls._instance
    
    @classmethod
    def reset_instance(cls):
        """
        Reset singleton (for testing only).
        
        WARNING: Only use in tests. Do not call in production code.
        """
        with cls._lock:
            cls._instance = None
            logger.warning("RiskManager singleton reset (testing only)")
    
    def update_balance(self, new_balance: float) -> None:
        """
        Update account balance.
        
        Parameters
        ----------
        new_balance : float
            New account balance
        """
        with self._lock:
            self._balance = new_balance
            logger.debug("Account balance updated", balance=new_balance)
    
    def get_risk_snapshot(
        self,
        vix_level: Optional[float] = None,
        session: Optional[str] = None,
    ) -> dict:
        """
        Get complete risk snapshot for synthesis integration.
        
        This is called by analysis/synthesis.py to replace the
        hardcoded "current_drawdown": 0.0 placeholder.
        
        Parameters
        ----------
        vix_level : float, optional
            Current VIX level for adaptive multiplier
        session : str, optional
            Trading session for adaptive multiplier
            
        Returns
        -------
        dict
            Complete risk snapshot with:
            - drawdown: daily/weekly/total drawdown
            - circuit_breaker: state and trading_allowed flag
            - risk_multiplier: overall multiplier and breakdown
            - prop_firm: compliance status
        """
        with self._lock:
            # Get drawdown snapshot
            dd_snapshot = self._drawdown.get_snapshot()
            
            # Get circuit breaker snapshot
            cb_snapshot = self._circuit_breaker.get_snapshot()
            
            # Calculate risk multiplier
            # Use total drawdown % as drawdown level
            drawdown_level = dd_snapshot["total_dd_percent"] / (
                self._drawdown.max_total_percent or 1.0
            )
            
            rm_overall = self._risk_multiplier.calculate(
                drawdown_level=drawdown_level,
                vix_level=vix_level,
                session=session,
            )
            
            rm_breakdown = self._risk_multiplier.get_breakdown(
                drawdown_level=drawdown_level,
                vix_level=vix_level,
                session=session,
            )
            
            # Combine into snapshot
            return {
                "drawdown": dd_snapshot,
                "circuit_breaker": cb_snapshot,
                "risk_multiplier": {
                    "overall": rm_overall,
                    "breakdown": rm_breakdown,
                },
                "balance": self._balance,
            }
    
    def record_trade_result(
        self,
        pnl: float,
        pair: str,
        current_equity: float,
    ) -> None:
        """
        Record a trade result and update all risk components.
        
        Parameters
        ----------
        pnl : float
            Trade profit/loss
        pair : str
            Trading pair
        current_equity : float
            Current account equity after trade
        """
        with self._lock:
            # Update drawdown
            self._drawdown.update(current_equity, pnl)
            
            # Get daily loss for circuit breaker
            dd_snapshot = self._drawdown.get_snapshot()
            daily_loss = dd_snapshot["daily_dd_amount"]
            
            # Update circuit breaker
            self._circuit_breaker.record_trade(pnl, pair, daily_loss)
            
            # Update balance
            self._balance = current_equity
            
            logger.info(
                "Trade result recorded",
                pair=pair,
                pnl=pnl,
                equity=current_equity,
                daily_loss=daily_loss,
            )
    
    def calculate_position(
        self,
        entry_price: float,
        stop_loss_price: float,
        pair: str,
        risk_percent: Optional[float] = None,
        vix_level: Optional[float] = None,
        session: Optional[str] = None,
    ) -> dict:
        """
        Calculate position size with adaptive risk multiplier.
        
        Parameters
        ----------
        entry_price : float
            Entry price
        stop_loss_price : float
            Stop loss price
        pair : str
            Trading pair
        risk_percent : float, optional
            Base risk % (uses default if None)
        vix_level : float, optional
            Current VIX for multiplier
        session : str, optional
            Trading session for multiplier
            
        Returns
        -------
        dict
            Position sizing details including lot_size
        """
        with self._lock:
            # Get current drawdown level
            dd_snapshot = self._drawdown.get_snapshot()
            drawdown_level = dd_snapshot["total_dd_percent"] / (
                self._drawdown.max_total_percent or 1.0
            )
            
            # Calculate risk multiplier
            risk_multiplier = self._risk_multiplier.calculate(
                drawdown_level=drawdown_level,
                vix_level=vix_level,
                session=session,
            )
            
            # Calculate position size
            position = self._position_sizer.calculate(
                account_balance=self._balance,
                entry_price=entry_price,
                stop_loss_price=stop_loss_price,
                pair=pair,
                risk_percent=risk_percent,
                risk_multiplier=risk_multiplier,
            )
            
            logger.debug(
                "Position calculated",
                pair=pair,
                lot_size=position["lot_size"],
                risk_multiplier=risk_multiplier,
            )
            
            return position
    
    def is_trading_allowed(self, category: Optional[str] = None) -> bool:
        """
        Check if trading is allowed based on all risk factors.
        
        Checks:
        - Circuit breaker state
        - Drawdown limits
        - Prop firm rules (if category provided)
        
        Parameters
        ----------
        category : str, optional
            Market category for prop firm check (e.g., "forex")
            
        Returns
        -------
        bool
            True if trading allowed
        """
        with self._lock:
            # Check circuit breaker
            if not self._circuit_breaker.is_trading_allowed():
                logger.warning(
                    "Trading not allowed: circuit breaker open",
                    state=self._circuit_breaker.get_state(),
                )
                return False
            
            # Check drawdown limits
            if self._drawdown.is_breached():
                logger.warning(
                    "Trading not allowed: drawdown limit breached",
                    snapshot=self._drawdown.get_snapshot(),
                )
                return False
            
            # Check prop firm rules
            if category and not self._prop_firm.is_market_allowed(category):
                logger.warning(
                    "Trading not allowed: market not allowed by prop firm",
                    category=category,
                )
                return False
            
            return True
    
    def check_prop_firm_compliance(self, trade_risk: dict) -> dict:
        """
        Check prop firm compliance for a proposed trade.
        
        Parameters
        ----------
        trade_risk : dict
            Trade details with:
            - risk_percent: Risk % for this trade
            - rr_ratio: Risk/reward ratio
            
        Returns
        -------
        dict
            Compliance result with:
            - compliant: bool
            - violations: list of violation messages
        """
        violations = []
        
        # Check risk per trade
        max_risk = self._prop_firm.max_risk_allowed()
        if trade_risk.get("risk_percent", 0) > max_risk:
            violations.append(
                f"Risk {trade_risk['risk_percent']*100:.2f}% "
                f"exceeds max {max_risk*100:.2f}%"
            )
        
        # Check min RR
        min_rr = self._prop_firm.min_rr_required()
        if trade_risk.get("rr_ratio", 0) < min_rr:
            violations.append(
                f"RR {trade_risk['rr_ratio']:.2f} "
                f"below min {min_rr:.2f}"
            )
        
        compliant = len(violations) == 0
        
        if not compliant:
            logger.warning(
                "Prop firm compliance check failed",
                violations=violations,
            )
        
        return {
            "compliant": compliant,
            "violations": violations,
        }
    
    def get_component(self, name: str):
        """
        Get direct access to a risk component (for advanced usage).
        
        Parameters
        ----------
        name : str
            Component name: "drawdown"|"circuit_breaker"|"position_sizer"|
            "risk_multiplier"|"prop_firm"
            
        Returns
        -------
        object
            The requested component
            
        Raises
        ------
        ValueError
            If component name is invalid
        """
        components = {
            "drawdown": self._drawdown,
            "circuit_breaker": self._circuit_breaker,
            "position_sizer": self._position_sizer,
            "risk_multiplier": self._risk_multiplier,
            "prop_firm": self._prop_firm,
        }
        
        if name not in components:
            raise ValueError(
                f"Invalid component: {name}. "
                f"Valid: {list(components.keys())}"
            )
        
        return components[name]
