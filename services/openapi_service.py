"""Bounded OpenAPI/Swagger import, without fetching external references."""
import json
import yaml


class NoAliasLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ValueError('YAML aliases are not supported. Upload an expanded document.')
        return super().compose_node(parent, index)


def parse_specification(content: str):
    if len(content.encode('utf-8')) > 256000:
        raise ValueError('OpenAPI documents must be smaller than 256 KB.')
    try:
        data = yaml.load(content, Loader=NoAliasLoader)
    except (yaml.YAMLError, RecursionError):
        raise ValueError('Upload valid OpenAPI JSON or YAML.') from None
    if not isinstance(data, dict) or not (str(data.get('openapi', '')).startswith('3.') or data.get('swagger') == '2.0'):
        raise ValueError('Expected an OpenAPI 3.x or Swagger 2.0 document.')
    if not isinstance(data.get('paths'), dict) or not data['paths']:
        raise ValueError('The specification must include at least one path.')
    def inspect(value, depth=0):
        if depth > 30:
            raise ValueError('Specification nesting exceeds 30 levels.')
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    # YAML turns unquoted response codes into integers; normalize below.
                    if not isinstance(key, int):
                        raise ValueError('Specification keys must be text or HTTP status numbers.')
                if key == '$ref' and (not isinstance(item, str) or not item.startswith('#/')):
                    raise ValueError('External references are not supported. Bundle references into the document.')
                inspect(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                inspect(item, depth + 1)
        elif value is not None and not isinstance(value, (str, int, float, bool)):
            raise ValueError('Use JSON-compatible values in the specification.')
    inspect(data)
    data = json.loads(json.dumps(data, allow_nan=False))
    operations = []
    for path, methods in data['paths'].items():
        if not isinstance(methods, dict):
            raise ValueError('Every path must contain an operation object.')
        for method, info in methods.items():
            if method.upper() in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'):
                operations.append({'method': method.upper(), 'endpoint': path, 'summary': info.get('summary', '') if isinstance(info, dict) else ''})
    if not operations or len(operations) > 100:
        raise ValueError('Import between 1 and 100 API operations.')
    return data, operations
