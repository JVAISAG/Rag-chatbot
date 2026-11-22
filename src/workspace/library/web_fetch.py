"""Fetch public articles while pinning each connection to a validated address."""
from dataclasses import dataclass
import http.client
import ipaddress
import queue
import socket
import ssl
import threading
import time
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
import certifi


MAX_BYTES = 10 * 1024 * 1024
TIMEOUT = 30.0
MAX_REDIRECTS = 3


class UnsafeURL(ValueError):
    """The URL or its destination is not a permitted public resource."""


class FetchError(ValueError):
    """The remote response could not be safely retrieved."""


@dataclass(frozen=True)
class FetchedPage:
    url: str
    content_type: str
    content: bytes


def validate_url(url):
    if not isinstance(url, str) or not url or len(url) > 4096 or any(ord(ch) <= 32 or ord(ch) == 127 for ch in url):
        raise UnsafeURL("Enter a valid public HTTP or HTTPS URL.")
    try:
        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username is not None or parts.password is not None:
            raise ValueError
        host = parts.hostname.encode("idna").decode("ascii").lower()
        port = parts.port if parts.port is not None else (443 if parts.scheme.lower() == "https" else 80)
        if not 1 <= port <= 65535 or '%' in host or '\\' in host:
            raise ValueError
        formatted_host = f"[{host}]" if ':' in host else host
        netloc = formatted_host + (f":{port}" if port != (443 if parts.scheme.lower() == "https" else 80) else "")
        target = quote(parts.path or '/', safe="/%:@!$&'()*+,;=-._~")
        query = quote(parts.query, safe="/%?:@!$&'()*+,;=-._~")
        canonical = urlunsplit((parts.scheme.lower(), netloc, target, query, ''))
        return canonical, host, port
    except (ValueError, UnicodeError):
        raise UnsafeURL("Enter a valid public HTTP or HTTPS URL without credentials.") from None


def public_address(address):
    if '%' in address:
        return False
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if not ip.is_global or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        # Exclude translated/tunnelled addresses which can conceal IPv4 targets.
        return (ip in ipaddress.ip_network('2000::/3') and ip.ipv4_mapped is None
                and ip not in ipaddress.ip_network('2002::/16')
                and ip not in ipaddress.ip_network('2001::/32'))
    return True


def resolve_public(host, port, deadline):
    """Bound DNS time and reject mixed public/private answers, without a second lookup."""
    result = queue.Queue(maxsize=1)
    def resolve():
        try:
            result.put((socket.getaddrinfo(host, port, type=socket.SOCK_STREAM), None))
        except OSError as error:
            result.put((None, error))
    threading.Thread(target=resolve, daemon=True).start()
    try:
        records, error = result.get(timeout=max(0, deadline - time.monotonic()))
    except queue.Empty:
        raise FetchError("The URL lookup timed out.") from None
    if error or not records:
        raise FetchError("The URL could not be resolved.") from None
    addresses = []
    for family, _, _, _, sockaddr in records:
        if family not in (socket.AF_INET, socket.AF_INET6) or not public_address(sockaddr[0]):
            raise UnsafeURL("The URL must resolve only to public addresses.")
        item = (family, sockaddr[0])
        if item not in addresses:
            addresses.append(item)
    return addresses


def _request(url, host, port, addresses, deadline):
    parts = urlsplit(url)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise FetchError("The article request timed out.")
    sock = None
    for family, address in addresses:
        candidate = socket.socket(family, socket.SOCK_STREAM)
        candidate.settimeout(max(0.001, deadline - time.monotonic()))
        try:
            candidate.connect((address, port))
            sock = candidate
            break
        except OSError:
            candidate.close()
    if sock is None:
        raise FetchError("The article could not be reached.")
    holder = [sock]
    def interrupt():
        try:
            holder[0].shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
    timer = threading.Timer(max(0.001, deadline - time.monotonic()), interrupt)
    timer.daemon = True
    timer.start()
    connection = None
    try:
        if parts.scheme == 'https':
            sock = ssl.create_default_context(cafile=certifi.where()).wrap_socket(sock, server_hostname=host)
            holder[0] = sock
        connection = http.client.HTTPConnection(host, port, timeout=max(0.001, deadline - time.monotonic()))
        connection.sock = sock
        path = parts.path + ('?' + parts.query if parts.query else '')
        connection.request('GET', path, headers={'Host': parts.netloc, 'Accept': 'text/html,application/pdf',
            'Accept-Encoding': 'identity', 'User-Agent': 'ResearchWorkspace/1.0', 'Connection': 'close'})
        response = connection.getresponse()
        headers = {name.lower(): value for name, value in response.getheaders()}
        if response.status in {301, 302, 303, 307, 308}:
            return response.status, headers, b''
        if response.status != 200:
            raise FetchError("The site did not return an article.")
        if headers.get('content-encoding', 'identity').strip().lower() not in {'', 'identity'}:
            raise FetchError("Compressed responses are not supported.")
        try:
            declared = int(headers.get('content-length', '0'))
        except ValueError:
            raise FetchError("The article has an invalid size.") from None
        if declared < 0 or declared > MAX_BYTES:
            raise FetchError("The article exceeds the 10 MB limit.")
        chunks, total = [], 0
        while True:
            if time.monotonic() >= deadline:
                raise FetchError("The article request timed out.")
            block = response.read1(min(65536, MAX_BYTES + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
            if total > MAX_BYTES:
                raise FetchError("The article exceeds the 10 MB limit.")
        if 'content-length' in headers and total != declared:
            raise FetchError("The article response was incomplete.")
        return response.status, headers, b''.join(chunks)
    except (OSError, http.client.HTTPException, ssl.SSLError):
        raise FetchError("The article could not be retrieved.") from None
    finally:
        timer.cancel()
        if connection is not None:
            connection.close()
        else:
            sock.close()


def fetch_public_url(url, *, resolver=resolve_public, request=_request, timeout=TIMEOUT):
    deadline = time.monotonic() + timeout
    current = url
    for hop in range(MAX_REDIRECTS + 1):
        current, host, port = validate_url(current)
        addresses = resolver(host, port, deadline)
        status, headers, content = request(current, host, port, addresses, deadline)
        if status in {301, 302, 303, 307, 308}:
            if hop == MAX_REDIRECTS or not headers.get('location'):
                raise FetchError("The article has too many redirects or an invalid redirect.")
            if any(ord(ch) <= 32 or ord(ch) == 127 for ch in headers['location']):
                raise UnsafeURL("The article redirect is invalid.")
            current = urljoin(current, headers['location'])
            continue
        content_type = headers.get('content-type', '').split(';', 1)[0].strip().lower()
        if content_type not in {'text/html', 'application/xhtml+xml', 'application/pdf'}:
            raise FetchError("The URL must return an HTML article or PDF.")
        if not content:
            raise FetchError("The article is empty.")
        return FetchedPage(current, content_type, content)
    raise FetchError("The article has too many redirects.")
