import json
from types import SimpleNamespace
import pytest
from models.schemas import APIInput
from services.ai_service import AIService, AIError


class FakeClient:
    def __init__(self, outputs, calls):
        self.outputs = outputs
        self.calls = calls
        self.responses = self
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def create(self, **kwargs):
        self.calls.append(kwargs)
        result = self.outputs.pop(0)
        if isinstance(result, Exception):
            raise result
        return FakeStream(result)


class FakeStream:
    def __init__(self, result):
        self.result = result
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def __iter__(self):
        yield SimpleNamespace(type='response.output_text.delta', delta=self.result)
        yield SimpleNamespace(type='response.completed', response=SimpleNamespace(output_text=self.result))


def service(outputs):
    calls = []
    return AIService('qwen3.5-397b', client_factory=lambda **kw: FakeClient(outputs, calls)), calls


def test_valid_and_repaired_generation(suite_data):
    ai, calls = service(['not json', json.dumps(suite_data)])
    result = ai.generate(APIInput(api_description='GET /health returns 200'))
    assert len(result.test_cases) == 1
    assert len(calls) == 2
    assert calls[0]['store'] is False
    assert calls[0]['stream'] is True
    assert 'schema' in calls[0]['input']


def test_bad_output_never_accepted():
    ai, calls = service(['{}', '```json\n{}\n```'])
    with pytest.raises(AIError, match='repair'):
        ai.generate(APIInput(api_description='GET /health'))
    assert len(calls) == 2


def test_provider_error_does_not_leak():
    ai, _ = service([RuntimeError('api-key=do-not-disclose')])
    with pytest.raises(AIError) as error:
        ai.generate(APIInput(api_description='GET /health'))
    assert 'do-not-disclose' not in str(error.value)


def test_missing_key(monkeypatch):
    monkeypatch.delenv('ADAPTION_API_KEY', raising=False)
    with pytest.raises(AIError, match='not configured'):
        AIService('model').generate(APIInput(api_description='GET /health'))


def test_analysis_only_uses_failed_ids():
    ai, _ = service([json.dumps({'summary': 'Hypothesis', 'hypotheses': [{'test_id': 'invented', 'hypothesis': 'Unknown', 'debugging_steps': []}]})])
    run = {'suite': {'api_name': 'Fixture'}, 'data': {'results': [{'id': 'TC-FAIL', 'status': 'failed'}]}}
    with pytest.raises(AIError, match='unknown test ID'):
        ai.analyse(run)


def test_successful_run_does_not_call_provider():
    ai, calls = service([])
    analysis = ai.analyse({'data': {'results': [{'id': 'TC-OK', 'status': 'passed'}]}})
    assert analysis['source'] == 'deterministic'
    assert calls == []


def test_incomplete_stream_rejected(suite_data):
    class IncompleteStream(FakeStream):
        def __iter__(self):
            yield SimpleNamespace(type='response.output_text.delta', delta=self.result)
    class IncompleteClient(FakeClient):
        def create(self, **kwargs):
            return IncompleteStream(json.dumps(suite_data))
    ai = AIService('model', client_factory=lambda **kw: IncompleteClient([], []))
    with pytest.raises(AIError, match='request failed'):
        ai.generate(APIInput(api_description='GET /health'))
