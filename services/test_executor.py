"""Bounded child-process runner with one active run per application process."""
__test__ = False
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
RUN_LOCK = threading.BoundedSemaphore(1)


def execute_suite(suite, options, local_origins, deadline=90):
    started = time.monotonic()
    worker = Path(__file__).with_name('worker.py')
    env = {k: v for k, v in os.environ.items() if k.upper() in ('SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'LANG')}
    payload = json.dumps({'suite': suite, 'options': options, 'local_origins': local_origins})
    try:
        process = subprocess.run([sys.executable, '-I', str(worker)], input=payload.encode('utf-8'), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=deadline, cwd=str(worker.parent.parent), env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if process.returncode != 0:
            raise RuntimeError('Worker stopped.')
        return json.loads(process.stdout)
    except (subprocess.TimeoutExpired, RuntimeError, ValueError, OSError):
        return {'summary': {'total': len(suite['test_cases']), 'passed': 0, 'failed': 0, 'skipped': 0, 'error': len(suite['test_cases']), 'duration_ms': round((time.monotonic() - started) * 1000, 2), 'requests': None}, 'results': [dict(id=c['id'], scenario=c['scenario'], method=c['method'], endpoint=c['endpoint'], category=c['category'], expected=c['expected'], actual=None, status='error', reason='Worker stopped or exceeded its deadline. Outcome is unknown; earlier requests may have reached the API.', failures=[], attempts=[]) for c in suite['test_cases']]}
