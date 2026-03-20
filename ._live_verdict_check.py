import os
import subprocess
import time

import requests
from dotenv import load_dotenv

load_dotenv()
env = os.environ.copy()
env["PORT"] = "8011"

p = subprocess.Popen(
    [
        r"c:/Users/INTEL/OneDrive/Documents/GitHub/TUYUL-FX-WOLF-15LAYER-SYSTEM/.venv/Scripts/python.exe",
        "api_server.py",
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    env=env,
)

time.sleep(10)
key = os.getenv("DASHBOARD_API_KEY", "")
url = "http://127.0.0.1:8011/api/v1/internal/verdict/path?pair=EURUSD"
headers = {"X-Forwarded-Proto": "https"}
if key:
    headers["Authorization"] = f"Bearer {key}"

try:
    r = requests.get(url, headers=headers, timeout=15, allow_redirects=False)
    print("STATUS", r.status_code)
    print("LOCATION", r.headers.get("location"))
    print("BODY", r.text[:5000])
except Exception as e:
    print("REQ_ERR", repr(e))

time.sleep(1)
if p.poll() is None:
    p.terminate()
    try:
        p.wait(timeout=6)
    except Exception:
        p.kill()

out = ""
if p.stdout is not None:
    out = p.stdout.read()
print("LOG_TAIL_START")
lines = out.splitlines()
for line in lines[-120:]:
    print(line)
print("LOG_TAIL_END")
