import json
import pytest
from pydantic import ValidationError
from models.schemas import APIInput, Suite, RunInput, RequestSpec
from models.database import Database
from services.openapi_service import parse_specification
from services.redaction import redact, substitute


@pytest.mark.parametrize('data', [{}, {'api_description': ''}, {'api_description': 42}, {'endpoint': 'ftp://example.com'}, {'endpoint': '//example.com'}, {'endpoint': 'https://user:pass@example.com'}, {'endpoint': '/a?key=secret'}])
def test_invalid_api_input(data):
    with pytest.raises(ValidationError):
        APIInput.model_validate(data)


def test_valid_description_and_endpoint():
    assert APIInput(api_description='POST /login').method == 'GET'
    assert APIInput(endpoint='https://example.com/api').endpoint.endswith('/api')


@pytest.mark.parametrize('status', [99, 600, '200', True])
def test_invalid_statuses(suite_data, status):
    suite_data['test_cases'][0]['expected']['status_code'] = status
    with pytest.raises(ValidationError):
        Suite.model_validate(suite_data)


def test_unknown_status_not_executable(suite_data):
    suite_data['test_cases'][0]['expected']['status_code'] = None
    with pytest.raises(ValidationError):
        Suite.model_validate(suite_data)


def test_unique_ids(suite_data):
    suite_data['test_cases'] *= 2
    with pytest.raises(ValidationError):
        Suite.model_validate(suite_data)


@pytest.mark.parametrize('headers', [{'Host': 'localhost'}, {'Content-Length': '0'}, {'X-Test': 'hello\r\nHost: localhost'}])
def test_unsafe_headers(headers):
    with pytest.raises(ValidationError):
        RequestSpec(headers=headers)


def test_authorization_required():
    with pytest.raises(ValidationError):
        RunInput(base_url='https://example.com')


def test_credentials_are_placeholders():
    safe = redact({'headers': {'Authorization': 'Bearer actual-token'}, 'body': {'password': 'actual-password'}}, placeholders=True)
    assert 'actual-' not in json.dumps(safe)
    assert safe['body']['password'] == '${SECRET_PASSWORD}'
    assert substitute(safe['body'], {'SECRET_PASSWORD': 'runtime-value'}) == {'password': 'runtime-value'}
    with pytest.raises(ValueError):
        substitute(safe, {})


def test_redaction_preserves_response_schema_and_invalid_types():
    data = {'properties': {'token': {'type': 'string'}}, 'body': {'password': 42}}
    assert redact(data, placeholders=True) == data


def test_database_persistence_and_revision(tmp_path, suite_data):
    path = str(tmp_path / 'history.sqlite')
    db = Database(path)
    first = db.save_suite(suite_data, {})
    suite_data['summary'] = 'Edited revision'
    second = db.save_suite(suite_data, {}, project_id=db.suite(first)['project_id'], reviewed=True)
    reopened = Database(path)
    assert reopened.suite(first)['data']['summary'] == ''
    assert reopened.suite(second)['data']['summary'] == 'Edited revision'
    assert reopened.dashboard()['totals']['projects'] == 1


def test_openapi_yaml_and_json():
    data, operations = parse_specification('openapi: 3.0.3\ninfo: {title: Example, version: "1"}\npaths:\n  /health:\n    get:\n      responses:\n        200: {description: OK}')
    assert operations[0]['method'] == 'GET'
    assert parse_specification(json.dumps(data))[0] == data


@pytest.mark.parametrize('content', ['{}', 'not: [valid', 'openapi: 3.0.0\npaths: &p { /a: {get: {}}}\nextra: *p', '{"openapi":"3.0.0","paths":{"/a":{"get":{"$ref":"http://localhost/secret"}}}}'])
def test_bad_openapi(content):
    with pytest.raises(ValueError):
        parse_specification(content)
