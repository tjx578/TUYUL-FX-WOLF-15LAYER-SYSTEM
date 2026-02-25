"""Test the lifespan function directly."""
import asyncio
import os
import traceback

os.environ["PYTHONIOENCODING"] = "utf-8"

async def test_lifespan():
    print("=" * 60)
    print("Testing lifespan boot...")
    print("=" * 60)

    try:
        from api_server import app, lifespan
        print("Import OK")
    except Exception as e:
        print(f"Import FAILED: {e}")
        traceback.print_exc()
        return

    try:
        async with lifespan(app):
            print("\n" + "=" * 60)
            print("  LIFESPAN STARTUP SUCCESS")
            print("=" * 60)
    except Exception as e:
        print("\n" + "=" * 60)
        print(f"  LIFESPAN STARTUP FAILED: {type(e).__name__}: {e}")
        print("=" * 60)
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_lifespan())
