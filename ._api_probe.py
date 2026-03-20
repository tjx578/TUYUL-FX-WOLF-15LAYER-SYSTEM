import os
import subprocess
import time

from dotenv import load_dotenv

load_dotenv()
env = os.environ.copy()
env["PORT"] = "8012"

p = subprocess.Popen(
    [
        r"c:/Users/INTEL/OneDrive/Documents/GitHub/TUYUL-FX-WOLF-15LAYER-SYSTEM/.venv/Scripts/python.exe",
        "-u",
        "api_server.py",
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    env=env,
)

for _i in range(12):
    if p.poll() is not None:
        break
    time.sleep(1)

print("PROC_EXITED", p.poll() is not None)
print("RETURN_CODE", p.poll())

if p.poll() is None:
    p.terminate()
    try:
        p.wait(timeout=6)
    except Exception:
        p.kill()

out = p.stdout.read() if p.stdout is not None else ""
print("LOG_START")
print(out)
print("LOG_END")
