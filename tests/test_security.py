import socket
from unittest.mock import patch
import pytest
from services.network import validate_url, NetworkBlocked, PinnedHTTPConnection, build_url


@pytest.mark.parametrize('target', ['http://127.0.0.1', 'http://localhost', 'http://10.0.0.1', 'http://172.16.0.1', 'http://192.168.1.1', 'http://169.254.169.254', 'http://0.0.0.0', 'http://[::1]', 'http://[::ffff:127.0.0.1]', 'http://[64:ff9b::7f00:1]', 'http://2130706433', 'http://0x7f000001', 'http://metadata.google.internal', 'file:///etc/passwd', 'http://user:pass@example.com', 'http://example.com\\@localhost', 'http://100.64.0.1', 'http://224.0.0.1'])
def test_ssrf_blocks(target):
    with pytest.raises(NetworkBlocked):
        validate_url(target)


def test_mixed_dns_rejected():
    answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80)), (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 80))]
    with patch('socket.getaddrinfo', return_value=answers), pytest.raises(NetworkBlocked):
        validate_url('http://mixed.example')


def test_connection_uses_pinned_ip_without_second_resolution():
    with patch('socket.socket') as sock, patch('socket.getaddrinfo', side_effect=AssertionError('second DNS lookup')):
        connection = PinnedHTTPConnection('public.example', 80, '93.184.216.34', 2)
        connection.connect()
        sock.return_value.connect.assert_called_once_with(('93.184.216.34', 80))


def test_local_exception_exact_and_loopback_only(fixture_api):
    assert validate_url(fixture_api, [fixture_api])[1] == '127.0.0.1'
    with pytest.raises(NetworkBlocked):
        validate_url(fixture_api, ['http://127.0.0.1:1'])
    with pytest.raises(NetworkBlocked):
        validate_url('http://10.0.0.1', ['http://10.0.0.1'])


def test_cross_origin_endpoint_rejected():
    with pytest.raises(NetworkBlocked):
        build_url('https://example.com', 'http://169.254.169.254/')
