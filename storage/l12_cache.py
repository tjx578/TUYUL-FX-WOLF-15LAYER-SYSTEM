import json
import time

from storage.redis_client import redis_client

KEY_PREFIX = "L12:VERDICT:"
VERDICT_READY_CHANNEL = "events:l12_verdict_ready"


def set_verdict(pair: str, data: dict):
    redis_client.set(KEY_PREFIX + pair, json.dumps(data))
    event_payload = {
        "event": "VERDICT_READY",
        "pair": pair,
        "ts": time.time(),
    }
    try:
        redis_client.publish(VERDICT_READY_CHANNEL, json.dumps(event_payload))
    except Exception:
        pass


def get_verdict(pair: str):
    raw = redis_client.get(KEY_PREFIX + pair)
    return json.loads(raw) if raw else None
