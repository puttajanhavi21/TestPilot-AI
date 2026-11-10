"""Deterministic assertion engine, shared with the downloadable Pytest file."""
import copy
import json
import time
from services.network import build_url, http_request

MISSING = object()


def lookup(data, path):
    value = data
    if not path:
        return value
    for key in path.split('.'):
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and key.isdigit() and int(key) < len(value):
            value = value[int(key)]
        else:
            return MISSING
    return value


def evaluate(expected, actual):
    failures = []
    if actual['status_code'] != expected['status_code']:
        failures.append(f"Status: expected {expected['status_code']}, received {actual['status_code']}.")
    content_type = expected.get('content_type')
    if content_type and actual['headers'].get('content-type', '').split(';')[0].strip().lower() != content_type.lower():
        failures.append('Response Content-Type does not match the contract.')
    if expected.get('max_response_ms') and actual['elapsed_ms'] > expected['max_response_ms']:
        failures.append(f"Response took {actual['elapsed_ms']} ms; limit is {expected['max_response_ms']} ms.")
    for key, value in expected.get('headers', {}).items():
        if actual['headers'].get(key.lower()) != value:
            failures.append('Response header mismatch: ' + key)
    needs_json = expected.get('required_fields') or expected.get('rules') or (content_type and 'json' in content_type)
    if needs_json and not actual['is_json']:
        failures.append('Expected a valid JSON response.')
        return failures
    for field in expected.get('required_fields', []):
        if lookup(actual['json'], field) is MISSING:
            failures.append('Missing required response property: ' + field)
    types = {'string': str, 'number': (int, float), 'integer': int, 'boolean': bool, 'object': dict, 'array': list, 'null': type(None)}
    for rule in expected.get('rules', []):
        value = lookup(actual['json'], rule['path'])
        op, operand = rule['operator'], rule.get('value')
        if op == 'exists':
            ok = value is not MISSING
        elif op == 'not_exists':
            ok = value is MISSING
        elif value is MISSING:
            ok = False
        elif op == 'equals':
            # JSON booleans must not compare equal to integers, including inside objects/arrays.
            ok = json.dumps(value, sort_keys=True, separators=(',', ':')) == json.dumps(operand, sort_keys=True, separators=(',', ':'))
        elif op == 'type':
            ok = isinstance(value, types[operand]) and not (isinstance(value, bool) and operand in ('number', 'integer'))
        else:
            ok = type(value) in (int, float) and (value >= operand if op == 'min' else value <= operand)
        if not ok:
            failures.append('JSON rule failed: ' + (rule['path'] or '(root)') + ' ' + op)
    return failures


def execute_case(case, base_url, timeout=8, local_origins=(), runtime_headers=None):
    result = {'id': case['id'], 'scenario': case['scenario'], 'category': case['category'], 'method': case['method'], 'endpoint': case['endpoint'], 'expected': case['expected'], 'status': 'skipped', 'failures': [], 'actual': None, 'attempts': []}
    if not case.get('eligible') or case['expected'].get('status_code') is None:
        result['reason'] = case.get('skip_reason') or 'Not eligible: configure and review the expected result.'
        return result
    if '{' in case['endpoint'] or '}' in case['endpoint']:
        result['reason'] = 'Resolve the endpoint path parameters before execution.'
        return result
    try:
        url = build_url(base_url, case['endpoint'])
        request = copy.deepcopy(case['request'])
        headers = {} if request.get('auth_mode') == 'omit' else dict(runtime_headers or {})
        for key, value in request.get('headers', {}).items():
            headers = {k: v for k, v in headers.items() if k.lower() != key.lower()}
            headers[key] = value
        request['headers'] = headers
        for attempt in range(case.get('repeat', 1)):
            if attempt:
                time.sleep(0.15)
            actual = http_request(case['method'], url, request, timeout, local_origins)
            failures = evaluate(case['expected'], actual)
            result['attempts'].append({'elapsed_ms': actual['elapsed_ms'], 'status_code': actual['status_code'], 'failures': failures})
            result['actual'] = actual
            result['failures'].extend(f'Attempt {attempt + 1}: {f}' for f in failures)
        result['status'] = 'failed' if result['failures'] else 'passed'
    except (TimeoutError, OSError) as exc:
        result['status'] = 'error'
        result['reason'] = 'Request timed out.' if isinstance(exc, TimeoutError) else 'Network or TLS connection failed.'
    except Exception as exc:
        result['status'] = 'error'
        # Only locally constructed validation messages are returned.
        result['reason'] = str(exc) if isinstance(exc, ValueError) else 'HTTP protocol error: ' + type(exc).__name__
    return result
