"""
Script to issue Wolf-15 system queries and log raw responses for manual review.
"""

import json

import requests

# Base URL for the local API server (adjust if needed)
BASE_URL = "http://localhost:8000"

# List of queries to issue (as endpoint, params, description)
QUERIES = [
    # Candle history (monthly)
    ("/api/v1/prices/GBPJPY", None, "wolf15:candle:GBPJPY:MN:history"),
    ("/api/v1/prices/AUDJPY", None, "wolf15:candle:AUDJPY:MN:history"),
    ("/api/v1/prices/AUDUSD", None, "wolf15:candle:AUDUSD:MN:history"),
    ("/api/v1/prices/CADCHF", None, "wolf15:candle:CADCHF:MN:history"),
    # Tick stream (simulate as price fetch)
    ("/api/v1/prices/NZDUSD", None, "wolf15:tick:NZDUSD:stream"),
    ("/api/v1/prices/EURGBP", None, "wolf15:tick:EURGBP:stream"),
    # Macro regime hash (simulate as not directly mapped, placeholder)
    ("/api/v1/prices/EURCHF", None, "regime:macro:EURCHF:hash"),
    ("/api/v1/prices/GBPUSD", None, "regime:macro:GBPUSD:hash"),
    ("/api/v1/prices/NZDCHF", None, "regime:macro:NZDCHF:hash"),
    ("/api/v1/prices/USDCAD", None, "regime:macro:USDCAD:hash"),
]


def issue_query(endpoint, params=None):
    url = BASE_URL + endpoint
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


def main():
    results = []
    for endpoint, params, desc in QUERIES:
        print(f"\n--- Query: {desc} ---")
        result = issue_query(endpoint, params)
        print(json.dumps(result, indent=2))
        results.append({"desc": desc, "result": result})
    # Optionally, write all results to a file for review
    with open("wolf15_query_log.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nAll queries completed. Results saved to wolf15_query_log.json.")


if __name__ == "__main__":
    main()
