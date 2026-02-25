"""Quick test: import api_server and write result to a file."""
import sys, os, traceback

os.environ["PYTHONIOENCODING"] = "utf-8"

result_file = "_test_result.txt"

try:
    import api_server
    with open(result_file, "w") as f:
        f.write("SUCCESS\n")
        f.write(f"app: {api_server.app}\n")
except Exception as e:
    with open(result_file, "w") as f:
        f.write(f"FAILED: {type(e).__name__}: {e}\n")
        f.write(traceback.format_exc())
