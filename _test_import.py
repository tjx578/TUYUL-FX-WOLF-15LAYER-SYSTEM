"""Temporary script to test api_server import."""
import os
import sys
import traceback

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

print("=" * 60)
print("Testing api_server import...")
print("=" * 60)

try:
    import api_server
    print("\n\n" + "=" * 60)
    print("  SUCCESS: api_server imported OK")
    print("  app object:", api_server.app)
    print("=" * 60)
except Exception as e:
    print("\n\n" + "=" * 60)
    print(f"  FAILED: {e}")
    print("=" * 60)
    traceback.print_exc()
    sys.exit(1)
