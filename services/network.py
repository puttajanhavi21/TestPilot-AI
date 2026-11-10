"""Pinned-address HTTP transport. No redirects, proxies, cookies or code execution."""
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
import uuid
from urllib.parse import urlencode, urlsplit, urlunsplit

MAX_RESPONSE_BYTES = 262144


class NetworkBlocked(ValueError):
    pass


def origin(url):
    p = urlsplit(url)
    try:
        port = p.port or (443 if p.scheme == 'https' else 80)
    except ValueError:
        raise NetworkBlocked('Invalid URL port.') from None
    return p.scheme.lower(), (p.hostname or '').lower(), port


def validate_url(url, local_origins=()):
    if len(url) > 4096 or '\\' in url or any(ord(c) < 33 for c in url):
        raise NetworkBlocked('URL contains unsafe characters or exceeds the length limit.')
    p = urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.fragment:
        raise NetworkBlocked('Use an HTTP(S) URL without embedded credentials or fragments.')
    scheme, host, port = origin(url)
    if not 1 <= port <= 65535 or '%' in host:
        raise NetworkBlocked('Invalid target hostname or port.')
    if host.rstrip('.').lower() in ('metadata.google.internal', 'metadata', 'instance-data'):
        raise NetworkBlocked('Cloud metadata endpoints are blocked.')
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        ips = list(dict.fromkeys(info[4][0] for info in answers))
        addresses = [ipaddress.ip_address(ip) for ip in ips]
    except (socket.gaierror, ValueError):
        raise NetworkBlocked('The target hostname could not be resolved.') from None
    if not addresses:
        raise NetworkBlocked('The target has no usable IP addresses.')
    local_exception = origin(url) in [origin(x) for x in local_origins] and all(a.is_loopback for a in addresses)
    for address in addresses:
        # Reject mapped, transition and NAT64 addresses, including their embedded destinations.
        transitional = address.version == 6 and (address.ipv4_mapped or address.sixtofour or address.teredo or address in ipaddress.ip_network('64:ff9b::/96') or address in ipaddress.ip_network('64:ff9b:1::/48'))
        if not local_exception and (not address.is_global or address.is_multicast or transitional):
            raise NetworkBlocked('Target blocked: localhost, private, reserved and cloud metadata addresses are not allowed.')
    return p, ips[0]


def build_url(base_url, endpoint):
    base = urlsplit(base_url)
    p = urlsplit(endpoint)
    if p.scheme:
        if origin(endpoint) != origin(base_url):
            raise NetworkBlocked('Every test endpoint must use the authorized base URL origin.')
        return endpoint
    if not endpoint.startswith('/') or endpoint.startswith('//') or p.query or p.fragment:
        raise NetworkBlocked('Test endpoint must be an absolute path without query parameters or fragments.')
    return urlunsplit((base.scheme, base.netloc, p.path, '', ''))


class PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self.validated_ip = ip

    def connect(self):
        address = ipaddress.ip_address(self.validated_ip)
        self.sock = socket.socket(socket.AF_INET6 if address.version == 6 else socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.validated_ip, self.port))


class PinnedHTTPSConnection(PinnedHTTPConnection):
    default_port = 443

    def connect(self):
        super().connect()
        self.sock = ssl.create_default_context().wrap_socket(self.sock, server_hostname=self.host)


def http_request(method, url, request, timeout=8, local_origins=()):
    """Validate fresh DNS answers, then connect directly to one validated IP."""
    p, ip = validate_url(url, local_origins)
    headers = dict(request.get('headers', {}))
    forbidden = {'host', 'content-length', 'transfer-encoding', 'connection', 'proxy-authorization', 'proxy-connection', 'upgrade', 'accept-encoding'}
    for key, value in headers.items():
        if not isinstance(value, str) or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9a-zA-Z-]+", key) or key.lower() in forbidden or any(ord(c) < 32 or ord(c) > 255 for c in value):
            raise ValueError('Unsafe or reserved request header.')
    headers['Accept-Encoding'] = 'identity'
    headers.setdefault('User-Agent', 'TestPilot-AI/1.0')
    body, kind = request.get('body'), request.get('body_type', 'json')
    if kind == 'none' or body is None:
        encoded = None
    elif kind == 'json':
        encoded = json.dumps(body, allow_nan=False).encode('utf-8')
        if not any(k.lower() == 'content-type' for k in headers):
            headers['Content-Type'] = 'application/json'
    elif kind == 'form':
        encoded = urlencode(body).encode('utf-8')
        headers = {k: v for k, v in headers.items() if k.lower() != 'content-type'}
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    else:
        boundary = 'TestPilot' + uuid.uuid4().hex
        chunks = []
        for key, value in body.items():
            if any(c in str(key) for c in '\r\n"'):
                raise ValueError('Invalid multipart field name.')
            chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n')
        encoded = (''.join(chunks) + f'--{boundary}--\r\n').encode('utf-8')
        headers = {k: v for k, v in headers.items() if k.lower() != 'content-type'}
        headers['Content-Type'] = 'multipart/form-data; boundary=' + boundary
    if encoded and len(encoded) > 65536:
        raise ValueError('Expanded request exceeds 64 KiB.')
    query = urlencode(request.get('query', {}))
    path = (p.path or '/') + ('?' + query if query else '')
    _, _, port = origin(url)
    connection_class = PinnedHTTPSConnection if p.scheme == 'https' else PinnedHTTPConnection
    connection = connection_class(p.hostname, port, ip, timeout)
    start = time.monotonic()
    try:
        connection.request(method, path, body=encoded, headers=headers)
        response = connection.getresponse()
        response_headers = {k.lower(): v for k, v in response.getheaders()}
        if response_headers.get('content-encoding', 'identity').lower() != 'identity':
            raise ValueError('Compressed responses are not accepted; the server ignored Accept-Encoding: identity.')
        content_length = response_headers.get('content-length', '')
        if content_length.isdigit() and int(content_length) > MAX_RESPONSE_BYTES:
            raise ValueError('Response exceeds the 256 KiB safety limit.')
        content = bytearray()
        while True:
            remaining = timeout - (time.monotonic() - start)
            if remaining <= 0:
                raise TimeoutError('Request deadline exceeded.')
            if connection.sock:
                connection.sock.settimeout(remaining)
            chunk = response.read1(min(8192, MAX_RESPONSE_BYTES + 1 - len(content)))
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > MAX_RESPONSE_BYTES:
                raise ValueError('Response exceeds the 256 KiB safety limit.')
        elapsed = round((time.monotonic() - start) * 1000, 2)
        try:
            data = json.loads(content)
        except (ValueError, UnicodeDecodeError):
            data = None
        return {'status_code': response.status, 'headers': response_headers, 'json': data, 'is_json': data is not None or bytes(content).strip() == b'null', 'bytes': len(content), 'elapsed_ms': elapsed, 'redirect_followed': False}
    finally:
        connection.close()
