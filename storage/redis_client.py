"""
Redis Client Wrapper
"""

import os

import redis
from loguru import logger


class RedisClient:
    _instance = None

    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.client = redis.Redis.from_url(url, decode_responses=True)
        logger.info("Redis client initialized")

    def set(self, key: str, value: str, ex: int = None):
        self.client.set(key, value, ex=ex)

    def get(self, key: str):
        return self.client.get(key)

    def delete(self, key: str):
        self.client.delete(key)


# Singleton instance for imports
redis_client = RedisClient()
