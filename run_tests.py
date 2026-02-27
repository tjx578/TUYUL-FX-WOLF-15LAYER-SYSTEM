import subprocess
import sys

result = subprocess.run(
    [sys.executable, '-W', 'ignore', '-m', 'pytest',
     'tests/test_pipeline_automated.py',
     'tests/test_v11_sniper_pipeline_integration.py',
     'tests/test_ws_connection_stress.py',
     'tests/test_ws_five_channels.py',
     '--tb=no', '-q'],
    capture_output=True, text=True
)
last_stdout = result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout
print(last_stdout)
print('EXIT CODE:', result.returncode)
