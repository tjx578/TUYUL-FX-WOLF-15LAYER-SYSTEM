"""
Read-only Redis key scanner for market data discovery.
Analysis zone only — no execution side-effects.
"""
import os

import redis


def scan_keys(pattern: str = "*", host: str = "127.0.0.1", port: int = 6379) -> list[str]:
    """Scan Redis for keys matching pattern (non-blocking SCAN)."""
    r = redis.Redis(
        host=host,
        port=port,
        password=os.getenv("REDIS_PASSWORD"),
        decode_responses=True,
    )
    keys: list[str] = []
    cursor: int = 0
    while True:
        cursor, batch = r.scan(cursor=cursor, match=pattern, count=100)  # type: ignore[misc]
        keys.extend(batch) # type: ignore
        if cursor == 0:
            break
    return sorted(keys)


def discover_market_data_keys() -> dict[str, list[str]]:
    """Discover all market-data-related keys grouped by pattern."""
    patterns = {
        "CHF_upper": "*CHF*",
        "chf_lower": "*chf*",
        "price": "*price*",
        "candle": "*candle*",
        "ohlc": "*ohlc*",
        "stream": "*stream*",
        "bar": "*bar*",
    }
    results: dict[str, list[str]] = {}
    for label, pattern in patterns.items():
        found = scan_keys(pattern)
        if found:
            results[label] = found
    return results


if __name__ == "__main__":
    print("=== All Keys ===")
    all_keys = scan_keys("*")
    for k in all_keys:
        print(f"  {k}")
    print(f"\nTotal: {len(all_keys)} keys\n")

    print("=== Market Data Keys ===")
    grouped = discover_market_data_keys()
    if not grouped:
        print("  (no market data keys found)")
    for label, keys in grouped.items():
        print(f"\n  [{label}]")
        for k in keys:
            print(f"    {k}")
