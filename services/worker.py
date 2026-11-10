"""Fixed worker entry point: validated stdin data, never AI code."""
import json
import os
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from models.schemas import Suite, RequestSpec
from services.engine import execute_case
from services.redaction import redact, substitute


def apply_limits():
    if os.name == 'posix':
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


def run(payload):
    suite = Suite.model_validate(payload['suite']).model_dump()
    options = payload['options']
    secrets = options.get('secrets', {})
    runtime_headers = options.get('headers', {})
    redaction_values = list(secrets.values()) + list(runtime_headers.values())
    started = time.monotonic()
    results = []
    for case in suite['test_cases']:
        try:
            expanded = substitute(case, secrets) if case['eligible'] else case
            RequestSpec.model_validate(expanded['request'])
            result = execute_case(expanded, options['base_url'], options['timeout_seconds'], payload['local_origins'], runtime_headers)
        except ValueError as exc:
            result = {'id': case['id'], 'scenario': case['scenario'], 'category': case['category'], 'method': case['method'], 'endpoint': case['endpoint'], 'expected': case['expected'], 'actual': None, 'status': 'skipped', 'reason': str(exc), 'failures': [], 'attempts': []}
        if result.get('actual'):
            result['actual']['headers'] = {k: v for k, v in result['actual']['headers'].items() if k in ('content-type', 'content-length', 'retry-after', 'x-ratelimit-limit', 'x-ratelimit-remaining')}
            safe_json = redact(result['actual']['json'], redaction_values)
            result['actual']['json'] = safe_json if len(json.dumps(safe_json)) < 12000 else {'_notice': 'Response body omitted from history: exceeds 12 KB. Assertions used the full bounded response.'}
        results.append(redact(result, redaction_values))
    summary = {status: sum(r['status'] == status for r in results) for status in ('passed', 'failed', 'skipped', 'error')}
    summary.update(total=len(results), duration_ms=round((time.monotonic() - started) * 1000, 2), requests=sum(len(r['attempts']) for r in results))
    return {'summary': summary, 'results': results}


if __name__ == '__main__':
    apply_limits()
    output = run(json.loads(sys.stdin.buffer.read(512 * 1024)))
    sys.stdout.write(json.dumps(output, allow_nan=False))
