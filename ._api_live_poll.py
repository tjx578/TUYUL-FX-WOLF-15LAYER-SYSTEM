import os
import subprocess
import time

import requests
from dotenv import load_dotenv

load_dotenv()
env = os.environ.copy()
env["PORT"] = "8013"

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

key = os.getenv("DASHBOARD_API_KEY", "")
headers = {"X-Forwarded-Proto": "https"}
if key:
    headers["Authorization"] = f"Bearer {key}"
url = "http://127.0.0.1:8013/api/v1/internal/verdict/path?pair=EURUSD"

response = None
last_err = None
for i in range(18):
    time.sleep(3)
    try:
        r = requests.get(url, headers=headers, timeout=6, allow_redirects=False)
        response = r
        print("ATTEMPT", i + 1, "STATUS", r.status_code)
        if r.status_code < 500:
            break
    except Exception as e:
        last_err = repr(e)
        print("ATTEMPT", i + 1, "ERR", last_err)

if response is not None:
    print("FINAL_STATUS", response.status_code)
    print("FINAL_LOCATION", response.headers.get("location"))
    print("FINAL_BODY", response.text[:5000])
else:
    print("FINAL_ERR", last_err)

if p.poll() is None:
    p.terminate()
    try:
        p.wait(timeout=8)
    except Exception:
        p.kill()

out = p.stdout.read() if p.stdout is not None else ""
print("LOG_TAIL_START")
for line in out.splitlines()[-160:]:
    print(line)
print("LOG_TAIL_END")
