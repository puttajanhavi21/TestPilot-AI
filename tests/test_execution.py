import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
import pytest
from services.engine import execute_case, evaluate
from services.test_executor import execute_suite
from services.test_generator import generate_pytest


def options(target):
    return {'base_url': target, 'authorized': True, 'secrets': {}, 'headers': {}, 'timeout_seconds': 2}


def test_real_isolated_pass_fail_skip(suite_data, fixture_api):
    failed = copy.deepcopy(suite_data['test_cases'][0])
    failed['id'] = 'TC-FAIL'
    failed['expected']['status_code'] = 201
    skipped = copy.deepcopy(failed)
    skipped.update(id='TC-SKIP', eligible=False, skip_reason='Contract not supplied')
    suite_data['test_cases'] += [failed, skipped]
    output = execute_suite(suite_data, options(fixture_api), [fixture_api])
    assert [r['status'] for r in output['results']] == ['passed', 'failed', 'skipped']
    assert output['summary']['requests'] == 2
    assert output['results'][1]['actual']['status_code'] == 200
    assert 'Set-Cookie' not in json.dumps(output)
    assert 'never-persist-cookie' not in json.dumps(output)


@pytest.mark.parametrize('path,expected_status', [('/large', 'error'), ('/text', 'failed'), ('/slow', 'error')])
def test_size_json_timeout(suite_data, fixture_api, path, expected_status):
    case = suite_data['test_cases'][0]
    case['endpoint'] = path
    result = execute_case(case, fixture_api, timeout=1, local_origins=[fixture_api])
    assert result['status'] == expected_status


def test_redirect_never_followed(suite_data, fixture_api):
    case = suite_data['test_cases'][0]
    case.update(endpoint='/redirect', expected={'status_code': 302})
    result = execute_case(case, fixture_api, local_origins=[fixture_api])
    assert result['status'] == 'passed'
    assert result['actual']['redirect_followed'] is False


@pytest.mark.parametrize('method', ['POST', 'PUT', 'PATCH', 'DELETE'])
@pytest.mark.parametrize('kind', ['json', 'form', 'multipart'])
def test_request_methods_and_body_types(suite_data, fixture_api, method, kind):
    case = suite_data['test_cases'][0]
    case.update(method=method, endpoint='/echo', request={'body_type': kind, 'body': {'name': 'test'}, 'query': {'page': 2}}, expected={'status_code': 201, 'required_fields': ['received']})
    result = execute_case(case, fixture_api, local_origins=[fixture_api])
    assert result['status'] == 'passed'
    assert 'test' in result['actual']['json']['received']


def test_runtime_auth_and_redaction(suite_data, fixture_api):
    suite_data['test_cases'][0].update(endpoint='/secret', expected={'status_code': 200})
    config = options(fixture_api)
    config['headers'] = {'Authorization': 'Bearer runtime-confidential'}
    output = execute_suite(suite_data, config, [fixture_api])
    assert output['summary']['passed'] == 1
    assert 'runtime-confidential' not in json.dumps(output)
    assert 'never-persist-this' not in json.dumps(output)


def test_auth_omit(suite_data, fixture_api):
    case = suite_data['test_cases'][0]
    case['request']['auth_mode'] = 'omit'
    case['expected']['rules'] = [{'path': 'authenticated', 'operator': 'equals', 'value': False}]
    assert execute_case(case, fixture_api, local_origins=[fixture_api], runtime_headers={'Authorization': 'Bearer invalid'})['status'] == 'passed'


def test_worker_deadline_records_unknown(suite_data, fixture_api):
    with patch('services.test_executor.subprocess.run', side_effect=subprocess.TimeoutExpired('worker', 1)):
        output = execute_suite(suite_data, options(fixture_api), [fixture_api], deadline=1)
    assert output['summary']['error'] == 1
    assert output['summary']['passed'] == 0


def test_exported_pytest_really_runs(tmp_path, suite_data, fixture_api):
    script = tmp_path / 'test_export.py'
    suite_data['summary'] = "Untrusted text: '; __import__('os').system('invalid'); #"
    script.write_text(generate_pytest(suite_data), encoding='utf-8')
    env = dict(os.environ, TESTPILOT_BASE_URL=fixture_api, TESTPILOT_LOCAL_ORIGINS=fixture_api, TESTPILOT_AUTHORIZED='1')
    result = subprocess.run([sys.executable, '-m', 'pytest', str(script), '-q'], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '1 passed' in result.stdout


def test_exported_pytest_really_fails(tmp_path, suite_data, fixture_api):
    suite_data['test_cases'][0]['expected']['status_code'] = 418
    script = tmp_path / 'test_fail.py'
    script.write_text(generate_pytest(suite_data), encoding='utf-8')
    env = dict(os.environ, TESTPILOT_BASE_URL=fixture_api, TESTPILOT_LOCAL_ORIGINS=fixture_api, TESTPILOT_AUTHORIZED='1')
    result = subprocess.run([sys.executable, '-m', 'pytest', str(script), '-q'], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert 'expected 418, received 200' in result.stdout


def test_protocol_assertions():
    actual = {'status_code': 200, 'elapsed_ms': 20, 'headers': {'content-type': 'application/json'}, 'is_json': True, 'json': {'count': True}}
    expected = {'status_code': 200, 'max_response_ms': 1, 'required_fields': ['missing'], 'headers': {'x-required': 'yes'}, 'rules': [{'path': 'count', 'operator': 'type', 'value': 'integer'}]}
    assert len(evaluate(expected, actual)) == 4


def test_nested_boolean_not_equal_to_integer():
    actual = {'status_code': 200, 'elapsed_ms': 1, 'headers': {}, 'is_json': True, 'json': {'nested': [True]}}
    expected = {'status_code': 200, 'rules': [{'path': '', 'operator': 'equals', 'value': {'nested': [1]}}]}
    assert len(evaluate(expected, actual)) == 1
