"""URL import network boundaries without contacting external services."""
import socket
import time

import pytest
from src.workspace.library import web_fetch


@pytest.mark.parametrize('url', [
    'file:///etc/passwd', 'ftp://example.com/file', 'http://user:password@example.com/',
    'http://example.com:0/', 'http://example.com:70000/', 'http://example.com/\r\nHost:evil',
    'http://[fe80::1%25eth0]/', 'http://example.com\\@127.0.0.1/',
])
def test_invalid_urls_are_rejected(url):
    with pytest.raises(web_fetch.UnsafeURL):
        web_fetch.validate_url(url)


@pytest.mark.parametrize('address', ['127.0.0.1', '10.0.0.1', '169.254.169.254', '192.168.1.1',
    '100.64.0.1', '::1', 'fc00::1', 'fe80::1', '::ffff:127.0.0.1', '2002:7f00:1::', '64:ff9b::a00:1'])
def test_private_and_tunnel_addresses_are_rejected(address):
    assert not web_fetch.public_address(address)


def test_mixed_dns_answers_are_rejected(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 80)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 80)),
    ])
    with pytest.raises(web_fetch.UnsafeURL):
        web_fetch.resolve_public('example.com', 80, time.monotonic() + 2)


def test_redirect_is_revalidated_and_never_connected_to_private_address():
    visited = []
    def resolver(host, port, deadline):
        visited.append(host)
        if host == '127.0.0.1':
            raise web_fetch.UnsafeURL('private')
        return [(socket.AF_INET, '8.8.8.8')]
    def request(url, host, port, addresses, deadline):
        assert addresses == [(socket.AF_INET, '8.8.8.8')]
        return 302, {'location': 'http://127.0.0.1/admin'}, b''
    with pytest.raises(web_fetch.UnsafeURL):
        web_fetch.fetch_public_url('https://example.com', resolver=resolver, request=request)
    assert visited == ['example.com', '127.0.0.1']


def test_redirect_limit_and_final_content_type():
    resolver = lambda host, port, deadline: [(socket.AF_INET, '8.8.8.8')]
    with pytest.raises(web_fetch.FetchError):
        web_fetch.fetch_public_url('https://example.com', resolver=resolver,
            request=lambda *args: (302, {'location': '/again'}, b''))
    page = web_fetch.fetch_public_url('https://example.com/start#ignored', resolver=resolver,
        request=lambda *args: (200, {'content-type': 'text/html; charset=utf-8'}, b'<p>Research</p>'))
    assert page.url == 'https://example.com/start' and page.content_type == 'text/html'
    with pytest.raises(web_fetch.FetchError):
        web_fetch.fetch_public_url('https://example.com', resolver=resolver,
            request=lambda *args: (200, {'content-type': 'application/json'}, b'{}'))


def test_dns_lookup_is_bounded(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: time.sleep(0.3))
    with pytest.raises(web_fetch.FetchError):
        web_fetch.resolve_public('example.com', 80, time.monotonic() + 0.02)


@pytest.mark.parametrize('headers,blocks', [
    ([('Content-Encoding', 'gzip')], [b'data']),
    ([('Content-Length', str(web_fetch.MAX_BYTES + 1))], []),
    ([('Content-Length', '10')], [b'short', b'']),
    ([], [b'x' * (web_fetch.MAX_BYTES + 1)]),
])
def test_wire_response_limits_fail_closed(monkeypatch, headers, blocks):
    class FakeSocket:
        def settimeout(self, value): pass
        def connect(self, target): assert target == ('8.8.8.8', 80)
        def shutdown(self, how): pass
        def close(self): pass
    class FakeResponse:
        status = 200
        def getheaders(self): return headers
        def read1(self, size): return blocks.pop(0) if blocks else b''
    class FakeConnection:
        def __init__(self, *args, **kwargs): self.sock = None
        def request(self, method, path, headers):
            assert method == 'GET' and headers['Host'] == 'example.com' and headers['Accept-Encoding'] == 'identity'
        def getresponse(self): return FakeResponse()
        def close(self): pass
    monkeypatch.setattr(web_fetch.socket, 'socket', lambda *args: FakeSocket())
    monkeypatch.setattr(web_fetch.http.client, 'HTTPConnection', FakeConnection)
    with pytest.raises(web_fetch.FetchError):
        web_fetch._request('http://example.com/paper', 'example.com', 80,
            [(socket.AF_INET, '8.8.8.8')], time.monotonic() + 2)
