import os
import subprocess
import time
import requests
from dotenv import load_dotenv

load_dotenv()
key = os.getenv('DASHBOARD_API_KEY', '')
headers = {'X-Forwarded-Proto': 'https'}
if key:
    headers['Authorization'] = f'Bearer {key}'

p = subprocess.Popen([
    r'c:/Users/INTEL/OneDrive/Documents/GitHub/TUYUL-FX-WOLF-15LAYER-SYSTEM/.venv/Scripts/python.exe',
    '-m','uvicorn','api_server:app','--host','127.0.0.1','--port','8016','--log-level','warning'
], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

ready = False
for _ in range(20):
    time.sleep(1)
    try:
        rr = requests.get('http://127.0.0.1:8016/healthz', headers={'X-Forwarded-Proto':'https'}, timeout=2, allow_redirects=False)
        if rr.status_code in {200, 307, 401, 404}:
            ready = True
            break
    except Exception:
        pass

print('SERVER_READY', ready)
try:
    r = requests.get('http://127.0.0.1:8016/api/v1/internal/verdict/path?pair=EURUSD', headers=headers, timeout=20, allow_redirects=False)
    print('STATUS', r.status_code)
    print('BODY', r.text[:5000])
except Exception as e:
    print('REQ_ERR', repr(e))

if p.poll() is None:
    p.terminate()
    try:
        p.wait(timeout=8)
    except Exception:
        p.kill()

log = p.stdout.read() if p.stdout else ''
print('LOG_TAIL_START')
for line in log.splitlines()[-80:]:
    print(line)
print('LOG_TAIL_END')
