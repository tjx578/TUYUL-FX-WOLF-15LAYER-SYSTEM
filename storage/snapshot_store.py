"""
Snapshot Store
Stores L14 JSON snapshots (post-L12).
"""

import json
from datetime import datetime

from storage.redis_client import RedisClient


class SnapshotStore:
    def __init__(self):
        self.redis = RedisClient()

    def save(self, snapshot: dict):
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        key = f"snapshot:L14:{snapshot.get('symbol')}:{ts}"
        self.redis.set(key, json.dumps(snapshot))
        return key

    def load(self, key: str) -> dict:
        raw = self.redis.get(key)
        return json.loads(raw) if raw else None
# Placeholder
