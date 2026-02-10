"""
Position Sizer - Fixed-Fractional Risk Calculator

Calculates position size based on fixed-fractional risk method.
Supports forex pairs and commodities (XAUUSD, XAGUSD) with
proper pip value handling.
"""

from typing import Optional

from loguru import logger

from config_loader import load_risk
from risk.exceptions import InvalidPositionSize, RiskCalculationError


class PositionSizer:
    """
    Fixed-fractional position sizing calculator.
    
    Calculates lot size based on:
    - Account balance
    - Risk percent per trade
    - Entry price
    - Stop loss price
    - Instrument pip value
    - Risk multiplier (from drawdown state)
    
    Attributes
    ----------
    default_risk_percent : float
        Default risk % if not specified (e.g., 0.01 = 1%)
    min_lot_size : float
        Minimum allowed lot size (default 0.01)
    max_lot_size : float
        Maximum allowed lot size (default 10.0)
    pip_values : dict
        Pip values per standard lot for each instrument
    """
    
    def __init__(
        self,
        default_risk_percent: Optional[float] = None,
        min_lot_size: Optional[float] = None,
        max_lot_size: Optional[float] = None,
    ):
        """
        Initialize PositionSizer.
        
        Parameters
        ----------
        default_risk_percent : float, optional
            Default risk % (loaded from config if None)
        min_lot_size : float, optional
            Min lot size (loaded from config if None)
        max_lot_size : float, optional
            Max lot size (loaded from config if None)
        """
        self._config = load_risk()
        ps_config = self._config["position_sizing"]
        
        self.default_risk_percent = (
            default_risk_percent or ps_config["default_risk_percent"]
        )
        self.min_lot_size = min_lot_size or ps_config["min_lot_size"]
        self.max_lot_size = max_lot_size or ps_config["max_lot_size"]
        self.pip_values = ps_config["pip_values"]
        
        logger.info(
            "PositionSizer initialized",
            default_risk_pct=self.default_risk_percent * 100,
            min_lot=self.min_lot_size,
            max_lot=self.max_lot_size,
        )
    
    def _get_pip_value(self, pair: str) -> float:
        """
        Get pip value for a trading pair.
        
        Parameters
        ----------
        pair : str
            Trading pair (e.g., "EURUSD", "XAUUSD")
            
        Returns
        -------
        float
            Pip value per standard lot
            
        Raises
        ------
        RiskCalculationError
            If pair not found in config
        """
        pip_value = self.pip_values.get(pair)
        if pip_value is None:
            raise RiskCalculationError(
                f"Pip value not configured for pair: {pair}"
            )
        return pip_value
    
    def _get_pip_decimals(self, pair: str) -> int:
        """
        Get number of decimal places for pip calculation.
        
        Parameters
        ----------
        pair : str
            Trading pair
            
        Returns
        -------
        int
            Number of decimal places (5 for forex, 2-3 for commodities)
        """
        # Commodities use fewer decimals
        if pair in ["XAUUSD", "XAGUSD"]:
            return 2 if pair == "XAUUSD" else 3
        
        # JPY pairs use 3 decimals (0.001 = 1 pip)
        if "JPY" in pair:
            return 3
        
        # Standard forex uses 5 decimals (0.00001 = 1 pip)
        return 5
    
    def calculate(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss_price: float,
        pair: str,
        risk_percent: Optional[float] = None,
        risk_multiplier: float = 1.0,
    ) -> dict:
        """
        Calculate position size using fixed-fractional method.
        
        Parameters
        ----------
        account_balance : float
            Current account balance
        entry_price : float
            Entry price for the trade
        stop_loss_price : float
            Stop loss price
        pair : str
            Trading pair (e.g., "EURUSD")
        risk_percent : float, optional
            Risk % to use (uses default if None)
        risk_multiplier : float, optional
            Risk multiplier from drawdown state (default 1.0)
            
        Returns
        -------
        dict
            Contains:
            - lot_size: Calculated lot size
            - risk_amount: Dollar amount at risk
            - risk_percent: Effective risk %
            - pips_at_risk: Distance from entry to SL in pips
            - multiplier_applied: Risk multiplier used
            
        Raises
        ------
        InvalidPositionSize
            If inputs are invalid or calculation fails
        RiskCalculationError
            If pair not configured
        """
        # Validate inputs
        if account_balance <= 0:
            raise InvalidPositionSize("Account balance must be positive")
        
        if entry_price <= 0 or stop_loss_price <= 0:
            raise InvalidPositionSize(
                "Entry and stop loss prices must be positive"
            )
        
        if risk_multiplier <= 0 or risk_multiplier > 1:
            raise InvalidPositionSize(
                "Risk multiplier must be between 0 and 1"
            )
        
        # Use default risk if not specified
        base_risk_percent = risk_percent or self.default_risk_percent
        
        # Apply risk multiplier
        effective_risk_percent = base_risk_percent * risk_multiplier
        
        # Calculate risk amount
        risk_amount = account_balance * effective_risk_percent
        
        # Get pip value for pair
        pip_value = self._get_pip_value(pair)
        pip_decimals = self._get_pip_decimals(pair)
        
        # Calculate pips at risk
        price_diff = abs(entry_price - stop_loss_price)
        
        # For JPY pairs: 0.01 = 1 pip
        # For other forex: 0.0001 = 1 pip
        # For XAUUSD: 0.01 = 1 pip
        if "JPY" in pair:
            pip_multiplier = 100
        elif pair in ["XAUUSD", "XAGUSD"]:
            pip_multiplier = 100 if pair == "XAUUSD" else 1000
        else:
            pip_multiplier = 10000
        
        pips_at_risk = price_diff * pip_multiplier
        
        if pips_at_risk <= 0:
            raise InvalidPositionSize(
                f"Invalid stop loss: must differ from entry. "
                f"Entry={entry_price}, SL={stop_loss_price}"
            )
        
        # Calculate lot size
        # Formula: lot_size = risk_amount / (pips_at_risk * pip_value)
        lot_size = risk_amount / (pips_at_risk * pip_value)
        
        # Clamp to min/max bounds
        if lot_size < self.min_lot_size:
            logger.warning(
                "Calculated lot size below minimum, clamping",
                calculated=lot_size,
                min_lot=self.min_lot_size,
            )
            lot_size = self.min_lot_size
        
        if lot_size > self.max_lot_size:
            logger.warning(
                "Calculated lot size above maximum, clamping",
                calculated=lot_size,
                max_lot=self.max_lot_size,
            )
            lot_size = self.max_lot_size
        
        # Round to 2 decimal places (standard lot precision)
        lot_size = round(lot_size, 2)
        
        logger.debug(
            "Position size calculated",
            pair=pair,
            lot_size=lot_size,
            risk_amount=risk_amount,
            risk_pct=effective_risk_percent * 100,
            pips_at_risk=pips_at_risk,
            multiplier=risk_multiplier,
        )
        
        return {
            "lot_size": lot_size,
            "risk_amount": risk_amount,
            "risk_percent": effective_risk_percent,
            "pips_at_risk": pips_at_risk,
            "multiplier_applied": risk_multiplier,
            "entry_price": entry_price,
            "stop_loss_price": stop_loss_price,
            "pair": pair,
        }
    
    def validate_lot_size(self, lot_size: float) -> bool:
        """
        Validate that a lot size is within acceptable bounds.
        
        Parameters
        ----------
        lot_size : float
            Lot size to validate
            
        Returns
        -------
        bool
            True if valid
        """
        return self.min_lot_size <= lot_size <= self.max_lot_size
