import sys

import redis

# Configurable connection (edit as needed)
REDIS_HOST = "localhost"
REDIS_PORT = 6379
STREAM_KEY = "signal:stream"

if len(sys.argv) > 1:
    STREAM_KEY = sys.argv[1]

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT)

print(f"XRANGE {STREAM_KEY} - +")
try:
    entries = r.xrange(STREAM_KEY, min="-", max="+", count=100)
    if not entries:
        print("[empty]")
    for entry_id, fields in entries:
        print(f"ID: {entry_id.decode() if isinstance(entry_id, bytes) else entry_id}")
        for k, v in fields.items():
            k = k.decode() if isinstance(k, bytes) else k
            v = v.decode() if isinstance(v, bytes) else v
            print(f"  {k}: {v}")
        print("-")
except Exception as e:
    print(f"Error: {e}")
