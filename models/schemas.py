"""Versioned, closed schemas shared by AI, review, export and execution."""
import json
import re
from typing import Any, Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Method = Literal['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, allow_inf_nan=False)


def endpoint_value(value: str) -> str:
    if any(ord(c) < 32 for c in value) or '\\' in value or '${' in value:
        raise ValueError('Endpoint cannot contain control characters, backslashes or secret placeholders.')
    p = urlsplit(value)
    if p.username or p.password or p.fragment:
        raise ValueError('Endpoint must not contain credentials or a fragment.')
    if p.scheme and (p.scheme not in ('http', 'https') or not p.hostname):
        raise ValueError('Use an http:// or https:// endpoint.')
    if not p.scheme and (not value.startswith('/') or value.startswith('//')):
        raise ValueError('Use an absolute HTTP URL or a path beginning with one /.')
    if p.query:
        raise ValueError('Put query parameters in the query object, not in the endpoint URL.')
    return value


class RequestSpec(StrictModel):
    headers: dict[str, str] = Field(default_factory=dict, max_length=40)
    query: dict[str, Any] = Field(default_factory=dict, max_length=40)
    body: Any = None
    body_type: Literal['json', 'form', 'multipart', 'none'] = 'json'
    auth_mode: Literal['inherit', 'omit'] = 'inherit'

    @field_validator('headers')
    @classmethod
    def safe_headers(cls, headers):
        forbidden = {'host', 'content-length', 'transfer-encoding', 'connection', 'proxy-authorization', 'proxy-connection', 'upgrade', 'accept-encoding'}
        for key, value in headers.items():
            if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9a-zA-Z-]+", key) or key.lower() in forbidden:
                raise ValueError('Unsafe or reserved request header.')
            if any(ord(c) < 32 or ord(c) > 255 for c in value):
                raise ValueError('Header values must contain printable Latin-1 characters only.')
        return headers

    @model_validator(mode='after')
    def bounded_request(self):
        if len(json.dumps(self.model_dump())) > 65536:
            raise ValueError('Each request must be smaller than 64 KiB.')
        if self.body_type in ('form', 'multipart') and not isinstance(self.body, dict):
            raise ValueError('Form bodies must be JSON objects (text fields only).')
        if any(isinstance(v, (dict, list)) for v in self.query.values()):
            raise ValueError('Query values must be scalar values.')
        return self


class Rule(StrictModel):
    path: str = Field(max_length=200, description='Dot path in response JSON; empty means root. Array indexes supported.')
    operator: Literal['exists', 'not_exists', 'equals', 'type', 'min', 'max']
    value: Any = None

    @model_validator(mode='after')
    def valid_operand(self):
        if self.operator == 'type' and self.value not in ('string', 'number', 'integer', 'boolean', 'object', 'array', 'null'):
            raise ValueError('Unsupported JSON type.')
        if self.operator in ('min', 'max') and (type(self.value) not in (int, float)):
            raise ValueError('Numeric rules require a number.')
        return self


class Expected(StrictModel):
    status_code: int | None = Field(default=None, strict=True, ge=100, le=599)
    content_type: str | None = Field(default=None, max_length=100)
    required_fields: list[str] = Field(default_factory=list, max_length=30)
    headers: dict[str, str] = Field(default_factory=dict, max_length=30)
    rules: list[Rule] = Field(default_factory=list, max_length=30)
    max_response_ms: int | None = Field(default=None, strict=True, ge=1, le=60000)


class TestCase(StrictModel):
    __test__ = False
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,60}$')
    category: Literal['functional', 'negative', 'boundary', 'security', 'protocol', 'performance']
    scenario: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=1500)
    method: Method
    endpoint: str = Field(max_length=2000)
    request: RequestSpec = Field(default_factory=RequestSpec)
    expected: Expected
    priority: Literal['high', 'medium', 'low'] = 'medium'
    preconditions: list[str] = Field(default_factory=list, max_length=15)
    assumptions: list[str] = Field(default_factory=list, max_length=15)
    eligible: bool = False
    skip_reason: str = Field(default='', max_length=500)
    repeat: int = Field(default=1, strict=True, ge=1, le=3)

    _endpoint = field_validator('endpoint')(endpoint_value)

    @model_validator(mode='after')
    def executable_expectation(self):
        if self.eligible and self.expected.status_code is None:
            raise ValueError('Executable tests require a reviewed expected status code.')
        return self


class Suite(StrictModel):
    schema_version: Literal['1.0'] = '1.0'
    api_name: str = Field(min_length=1, max_length=100)
    summary: str = Field(default='', max_length=3000)
    assumptions: list[str] = Field(default_factory=list, max_length=30)
    clarification_questions: list[str] = Field(default_factory=list, max_length=30)
    test_cases: list[TestCase] = Field(min_length=1, max_length=25)

    @model_validator(mode='after')
    def unique_ids(self):
        ids = [c.id for c in self.test_cases]
        if len(set(ids)) != len(ids):
            raise ValueError('Test case IDs must be unique.')
        if len(json.dumps(self.model_dump(), allow_nan=False)) > 300000:
            raise ValueError('Suite data must fit within 300 KB.')
        return self


class APIInput(StrictModel):
    project_name: str = Field(default='Untitled API', min_length=1, max_length=100)
    api_description: str = Field(default='', max_length=15000)
    method: Method = 'GET'
    endpoint: str = Field(default='/', max_length=2000)
    request: RequestSpec = Field(default_factory=RequestSpec)
    specification: dict[str, Any] | None = None

    _endpoint = field_validator('endpoint')(endpoint_value)

    @model_validator(mode='after')
    def enough_context(self):
        if not self.api_description and not self.specification and self.endpoint == '/':
            raise ValueError('Provide an API description, endpoint, or OpenAPI specification.')
        return self


class RunInput(StrictModel):
    base_url: str = Field(max_length=2000)
    authorized: bool = False
    secrets: dict[str, str] = Field(default_factory=dict, max_length=30)
    headers: dict[str, str] = Field(default_factory=dict, max_length=30)
    timeout_seconds: int = Field(default=8, strict=True, ge=1, le=15)

    @model_validator(mode='after')
    def valid_run(self):
        endpoint_value(self.base_url)
        if not urlsplit(self.base_url).hostname:
            raise ValueError('Execution needs an absolute base URL.')
        if not self.authorized:
            raise ValueError('Confirm that you are authorized to test this API.')
        RequestSpec(headers=self.headers)
        if any(not re.fullmatch(r'[A-Z][A-Z0-9_]{0,59}', k) or not v or len(v) > 8192 for k, v in self.secrets.items()):
            raise ValueError('Secret names must use uppercase letters, digits and underscores; values must be nonempty and at most 8192 characters.')
        return self


class FailureHypothesis(StrictModel):
    test_id: str
    hypothesis: str = Field(max_length=2000)
    debugging_steps: list[str] = Field(max_length=10)


class Analysis(StrictModel):
    summary: str = Field(max_length=3000)
    hypotheses: list[FailureHypothesis] = Field(max_length=25)
