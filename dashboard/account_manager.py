"""
Account Manager — Simple multi-account store.

Provides:
  - create_account: Create new trading account
  - get_account: Retrieve account details
  - update_equity: Update account equity (balance + floating P&L)
  - list_accounts: List all accounts
  
Persistence:
  - Redis: ACCOUNT:{account_id}
  - In-memory cache for fast access
"""

import json
import os
from threading import Lock
from typing import Dict, List, Optional

from loguru import logger

from schemas.trade_models import Account
from storage.redis_client import RedisClient
from utils.timezone_utils import now_utc


class AccountManager:
    """
    Thread-safe account management service.
    
    Stores account information with balance, equity, and risk limits.
    Used by dashboard to compute safe lot sizes and enforce risk rules.
    """

    _instance: Optional["AccountManager"] = None
    _lock = Lock()

    def __new__(cls) -> "AccountManager":
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        """Initialize account manager."""
        self._redis = RedisClient()
        self._redis_prefix = os.getenv("REDIS_PREFIX", "wolf15")
        self._cache: Dict[str, Account] = {}
        self._rw_lock = Lock()
        
        # Load existing accounts from Redis on startup
        self._load_from_redis()
        
        logger.info("AccountManager initialized")

    def _load_from_redis(self) -> None:
        """Load all accounts from Redis into cache."""
        try:
            pattern = f"{self._redis_prefix}:ACCOUNT:*"
            client = self._redis.client
            
            cursor = 0
            loaded_count = 0
            
            while True:
                cursor, keys = client.scan(cursor, match=pattern, count=100)
                
                for key in keys:
                    account_json = self._redis.get(key)
                    if account_json:
                        account_data = json.loads(account_json)
                        # Parse datetime fields
                        account = Account(**account_data)
                        self._cache[account.account_id] = account
                        loaded_count += 1
                
                if cursor == 0:
                    break
            
            if loaded_count > 0:
                logger.info(f"Loaded {loaded_count} accounts from Redis")
                
        except Exception as exc:
            logger.error(f"Failed to load accounts from Redis: {exc}")

    def create_account(
        self,
        name: str,
        balance: float,
        prop_firm: bool = False,
        max_daily_dd_percent: float = 4.0,
        max_total_dd_percent: float = 8.0,
        max_concurrent_trades: int = 1,
    ) -> Account:
        """
        Create a new trading account.
        
        Args:
            name: Account name/label
            balance: Initial balance
            prop_firm: Is this a prop firm account?
            max_daily_dd_percent: Max daily drawdown %
            max_total_dd_percent: Max total drawdown %
            max_concurrent_trades: Max concurrent trades
            
        Returns:
            Created Account instance
        """
        # Generate account ID
        timestamp = int(now_utc().timestamp() * 1000)
        account_id = f"ACC-{timestamp}"
        
        # Create account
        account = Account(
            account_id=account_id,
            name=name,
            balance=balance,
            equity=balance,  # Initially equity = balance
            prop_firm=prop_firm,
            max_daily_dd_percent=max_daily_dd_percent,
            max_total_dd_percent=max_total_dd_percent,
            max_concurrent_trades=max_concurrent_trades,
        )
        
        # Store in cache and Redis
        with self._rw_lock:
            self._cache[account_id] = account
            
            try:
                redis_key = f"{self._redis_prefix}:ACCOUNT:{account_id}"
                self._redis.set(redis_key, account.model_dump_json())
                logger.info(f"Created account: {account_id} ({name})")
            except Exception as exc:
                logger.error(f"Failed to save account to Redis: {exc}")
        
        return account

    def get_account(self, account_id: str) -> Optional[Account]:
        """
        Get account by ID.
        
        Args:
            account_id: Account ID (e.g., "ACC-1234567890")
            
        Returns:
            Account instance if found, else None
        """
        with self._rw_lock:
            # Check cache first
            if account_id in self._cache:
                return self._cache[account_id]
            
            # Try Redis
            try:
                redis_key = f"{self._redis_prefix}:ACCOUNT:{account_id}"
                account_json = self._redis.get(redis_key)
                
                if account_json:
                    account_data = json.loads(account_json)
                    account = Account(**account_data)
                    self._cache[account_id] = account
                    return account
                    
            except Exception as exc:
                logger.error(f"Failed to get account from Redis: {exc}")
        
        return None

    def update_equity(self, account_id: str, equity: float) -> bool:
        """
        Update account equity (balance + floating P&L).
        
        Args:
            account_id: Account ID
            equity: New equity value
            
        Returns:
            True if updated successfully, False otherwise
        """
        with self._rw_lock:
            account = self.get_account(account_id)
            
            if not account:
                logger.warning(f"Account not found: {account_id}")
                return False
            
            # Update equity
            account.equity = equity
            
            # Save to cache and Redis
            self._cache[account_id] = account
            
            try:
                redis_key = f"{self._redis_prefix}:ACCOUNT:{account_id}"
                self._redis.set(redis_key, account.model_dump_json())
                logger.debug(f"Updated equity for {account_id}: {equity:.2f}")
                return True
            except Exception as exc:
                logger.error(f"Failed to update account equity in Redis: {exc}")
                return False

    def list_accounts(self) -> List[Account]:
        """
        List all accounts.
        
        Returns:
            List of all Account instances
        """
        with self._rw_lock:
            return list(self._cache.values())

    def get_account_count(self) -> int:
        """
        Get total number of accounts.
        
        Returns:
            Number of accounts
        """
        with self._rw_lock:
            return len(self._cache)


# Singleton instance for imports
account_manager = AccountManager()
