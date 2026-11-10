import io
import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from models.schemas import Suite
from services.ai_service import AIError


def test_home_and_empty_dashboard(client):
    page = client.get('/')
    assert page.status_code == 200
    assert 'Content-Security-Policy' in page.headers
    assert client.get('/api/dashboard').json['totals']['runs'] == 0


@pytest.mark.parametrize('payload', [{}, {'api_description': ''}, {'api_description': 42}, []])
def test_invalid_generation_requests(client, payload):
    assert client.post('/generate', json=payload).status_code == 400


def test_malformed_json(client):
    assert client.post('/generate', data='{invalid', content_type='application/json').status_code == 400


def test_csrf_and_host(app, client):
    assert app.test_client().post('/generate', json={}).status_code == 403
    assert client.post('/generate', json={}, headers={'Origin': 'https://attacker.example'}).status_code == 403
    assert client.get('/', headers={'Host': 'attacker.example'}).status_code == 400


def test_generation_provider_error(app, client):
    app.extensions['ai_service'] = Mock(generate=Mock(side_effect=AIError('Provider unavailable')))
    assert client.post('/generate', json={'api_description': 'GET /health'}).status_code == 502
    assert client.get('/api/suites').json['suites'] == []


def test_full_workflow_with_mocked_ai_real_http(app, client, suite_data, fixture_api, tmp_path):
    app.config['LOCAL_ORIGINS'] = [fixture_api]
    app.extensions['ai_service'] = Mock(generate=Mock(return_value=Suite.model_validate(suite_data)), analyse=Mock(return_value={'source': 'adaption', 'summary': 'Mocked analysis for test verification.', 'hypotheses': []}))
    generated = client.post('/generate', json={'api_description': 'GET /health returns 200 and status ok'}).json['suite']
    sid = generated['id']
    assert client.post(f'/api/suites/{sid}/run', json={'base_url': fixture_api, 'authorized': True}).status_code == 400
    reviewed = client.put(f'/api/suites/{sid}', json=generated['data']).json
    assert reviewed['id'] != sid
    result = client.post(f"/api/suites/{reviewed['id']}/run", json={'base_url': fixture_api, 'authorized': True})
    assert result.status_code == 200, result.json
    run = result.json
    assert run['data']['summary']['passed'] == 1
    rid = run['id']
    assert client.post(f'/api/runs/{rid}/analyse', json={}).status_code == 200
    assert client.get(f'/api/runs/{rid}').json['analysis']['source'] == 'adaption'
    assert client.get(f'/api/runs/{rid}/export.json').json['id'] == rid
    pdf = client.get(f'/api/runs/{rid}/export.pdf')
    assert pdf.status_code == 200 and pdf.data.startswith(b'%PDF-')
    assert b'%%EOF' in pdf.data
    export = client.get(f"/api/suites/{reviewed['id']}/export.py")
    assert export.status_code == 200
    compile(export.data, '<export>', 'exec')
    stats = client.get('/api/dashboard').json['totals']
    assert stats['runs'] == 1 and stats['passed'] == 1 and stats['generated_cases'] == 1
    assert stats['reports'] == 3
    assert client.get('/api/runs').json['runs'][0]['id'] == rid
    # Keep a real fixture report for visual quality verification, outside user history.
    Path('tmp/pdfs').mkdir(parents=True, exist_ok=True)
    Path('tmp/pdfs/fixture-report.pdf').write_bytes(pdf.data)


def test_private_url_blocked_by_route(client, suite_data):
    sid = client.post('/api/suites', json=suite_data).json['id']
    sid = client.put(f'/api/suites/{sid}', json=suite_data).json['id']
    result = client.post(f'/api/suites/{sid}/run', json={'base_url': 'http://127.0.0.1:5000', 'authorized': True})
    assert result.status_code == 400
    assert 'blocked' in result.json['error']


def test_credential_not_in_database(client, app, suite_data):
    suite_data['test_cases'][0]['request']['headers'] = {'Authorization': 'Bearer private-credential-marker'}
    result = client.post('/api/suites', json=suite_data)
    assert 'private-credential-marker' not in result.get_data(as_text=True)
    with app.extensions['database'].connect() as db:
        assert 'private-credential-marker' not in str([tuple(r) for r in db.execute('SELECT * FROM suites')])


def test_openapi_upload_and_missing_records(client):
    data = b'{"openapi":"3.0.3","paths":{"/health":{"get":{}}}}'
    response = client.post('/api/openapi', data={'file': (io.BytesIO(data), 'api.json')})
    assert response.status_code == 200
    assert response.json['operations'][0]['endpoint'] == '/health'
    assert client.get('/api/runs/999').status_code == 404
    assert client.get('/api/suites/999').status_code == 404


def test_edit_validation_is_non_persisting(client, suite_data):
    assert client.post('/api/validate-suite', json=suite_data).status_code == 200
    suite_data['test_cases'][0]['expected']['status_code'] = 700
    assert client.post('/api/validate-suite', json=suite_data).status_code == 400
    assert client.get('/api/suites').json['suites'] == []
