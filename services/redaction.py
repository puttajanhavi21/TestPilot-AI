"""Credentials are placeholders at rest and supplied only for an execution."""
import re
from typing import Any

SENSITIVE = re.compile(r'password|passwd|secret|token|authorization|api[-_]?key|cookie|credential', re.I)
PLACEHOLDER = re.compile(r'\$\{([A-Z][A-Z0-9_]{0,59})\}')


def scrub_text(text: str, secrets=()) -> str:
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, '[REDACTED]')
    text = re.sub(r'(?i)\b(Bearer|Basic)\s+(?!\$\{)[A-Za-z0-9._~+/=-]+', r'\1 [REDACTED]', text)
    text = re.sub(r'(?i)((?:password|passwd|api[_-]?key|secret|access[_-]?token)\s*[:=]\s*)(?!\$\{)[^\s,;"\}]+', r'\1[REDACTED]', text)
    return text


def redact(value: Any, secrets=(), placeholders=False) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if SENSITIVE.search(str(key)) and isinstance(item, str) and item != '':
                if isinstance(item, str) and PLACEHOLDER.search(item):
                    result[key] = item
                else:
                    name = re.sub('[^A-Z0-9_]', '_', str(key).upper())[:40]
                    result[key] = '${SECRET_' + name + '}' if placeholders else '[REDACTED]'
            else:
                result[key] = redact(item, secrets, placeholders)
        return result
    if isinstance(value, list):
        return [redact(item, secrets, placeholders) for item in value]
    if isinstance(value, str):
        return scrub_text(value, secrets)
    return value


def substitute(value: Any, secrets: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: substitute(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, secrets) for v in value]
    if isinstance(value, str):
        def replace(match):
            if match[1] not in secrets:
                raise ValueError('Missing execution secret: ' + match[1])
            return secrets[match[1]]
        return PLACEHOLDER.sub(replace, value)
    return value
