import json

from storage.redis_client import redis_client

KEY_PREFIX = "L12:VERDICT:"


def set_verdict(pair: str, data: dict):
    redis_client.set(KEY_PREFIX + pair, json.dumps(data))


def get_verdict(pair: str):
    raw = redis_client.get(KEY_PREFIX + pair)
    return json.loads(raw) if raw else None
