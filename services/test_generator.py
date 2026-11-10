"""Generate a standalone test module from reviewed data and trusted templates."""
__test__ = False
import json
from pathlib import Path


def generate_pytest(suite):
    root = Path(__file__).parent
    network = (root / 'network.py').read_text(encoding='utf-8')
    engine = (root / 'engine.py').read_text(encoding='utf-8').replace('from services.network import build_url, http_request\n', '')
    redaction = (root / 'redaction.py').read_text(encoding='utf-8')
    preamble = '''"""TestPilot AI standalone export.
Run: python -m pytest test_api.py -v
Required environment: TESTPILOT_BASE_URL and TESTPILOT_AUTHORIZED=1.
Optional: TESTPILOT_SECRETS (JSON), TESTPILOT_HEADERS (JSON).
Local fixture ONLY: TESTPILOT_LOCAL_ORIGINS (comma-separated exact origins).
Uses the same pinned-IP HTTP transport as the application.
Requires Python 3.11+ and pytest. Never run parallel workers against a target.
"""
import os
import pytest
'''
    data = '\nSUITE = json.loads(' + repr(json.dumps(suite, ensure_ascii=True)) + ')\n'
    tests = '''
@pytest.mark.parametrize("case", SUITE["test_cases"], ids=lambda case: case["id"])
def test_api(case):
    if os.getenv("TESTPILOT_AUTHORIZED") != "1":
        pytest.fail("Set TESTPILOT_AUTHORIZED=1 only for an API you are authorized to test.")
    base = os.getenv("TESTPILOT_BASE_URL", "")
    if not base:
        pytest.fail("Set TESTPILOT_BASE_URL to the authorized API origin.")
    local = [s.strip().rstrip("/") for s in os.getenv("TESTPILOT_LOCAL_ORIGINS", "").split(",") if s.strip()]
    secret_values = json.loads(os.getenv("TESTPILOT_SECRETS", "{}"))
    headers = json.loads(os.getenv("TESTPILOT_HEADERS", "{}"))
    try:
        expanded = substitute(case, secret_values) if case.get("eligible") else case
    except ValueError as error:
        pytest.skip(str(error))
    result = execute_case(expanded, base, local_origins=local, runtime_headers=headers)
    result = redact(result, list(secret_values.values()) + list(headers.values()))
    if result["status"] == "skipped":
        pytest.skip(result.get("reason", "Not eligible."))
    assert result["status"] == "passed", result.get("reason") or "; ".join(result["failures"])
'''
    return preamble + '\n' + network + '\n' + redaction + '\n' + engine + data + tests
