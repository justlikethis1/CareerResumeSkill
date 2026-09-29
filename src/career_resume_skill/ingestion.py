from __future__ import annotations

import asyncio
import http.client
import ipaddress
import re
import socket
import ssl
from email.message import Message
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

MAX_JD_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
ALLOWED_CONTENT_TYPES = ("text/html", "text/plain", "application/xhtml+xml")
JD_REQUEST_TIMEOUT_SECONDS = 20


def is_url(value: str) -> bool:
    return urlparse(value.strip()).scheme.lower() in {"http", "https"}


def _resolve_public_addresses(url: str) -> tuple[str, int, list[str]]:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("JD URL must use http or https and include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("JD URL must not contain credentials")
    try:
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError as error:
        raise ValueError("JD URL contains an invalid port") from error
    try:
        results = socket.getaddrinfo(
            parsed.hostname, port, type=socket.SOCK_STREAM
        )
    except socket.gaierror as error:
        raise ValueError(f"Unable to resolve JD URL hostname: {parsed.hostname}") from error
    addresses: list[str] = []
    for result in results:
        address = result[4][0]
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if not ip.is_global:
            raise ValueError("JD URL must resolve only to public network addresses")
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise ValueError(f"Unable to resolve JD URL hostname: {parsed.hostname}")
    return parsed.hostname, port, addresses


def validate_public_url(url: str) -> None:
    _resolve_public_addresses(url)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, hostname: str, address: str, port: int) -> None:
        super().__init__(hostname, port, timeout=JD_REQUEST_TIMEOUT_SECONDS)
        self.address = address

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self.address, self.port), self.timeout
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname: str, address: str, port: int) -> None:
        context = ssl.create_default_context()
        super().__init__(
            hostname, port, timeout=JD_REQUEST_TIMEOUT_SECONDS, context=context
        )
        self.address = address
        self.tls_context = context

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self.address, self.port), self.timeout
        )
        self.sock = self.tls_context.wrap_socket(
            raw_socket, server_hostname=self.host
        )


def _request_pinned(
    url: str, hostname: str, address: str, port: int
) -> tuple[int, dict[str, str], bytes, str | None]:
    parsed = urlparse(url)
    connection_type = (
        _PinnedHTTPSConnection if parsed.scheme.lower() == "https"
        else _PinnedHTTPConnection
    )
    connection = connection_type(hostname, address, port)
    path = parsed.path or "/"
    if parsed.params:
        path += f";{parsed.params}"
    if parsed.query:
        path += f"?{parsed.query}"
    try:
        connection.request(
            "GET",
            path,
            headers={
                "User-Agent": "CareerResumeSkill/0.1 (+local MCP client)",
                "Accept-Encoding": "identity",
            },
        )
        response = connection.getresponse()
        headers = {name.casefold(): value for name, value in response.getheaders()}
        if response.status in {301, 302, 303, 307, 308}:
            return response.status, headers, b"", None
        if not 200 <= response.status < 300:
            raise ValueError(f"JD URL returned HTTP status {response.status}")
        content_length = headers.get("content-length")
        if content_length is not None:
            try:
                content_length_value = int(content_length)
            except ValueError as error:
                raise ValueError("JD response has an invalid Content-Length") from error
            if content_length_value > MAX_JD_BYTES:
                raise ValueError("JD response exceeds the 2 MiB limit")
        content_encoding = headers.get("content-encoding", "identity").casefold()
        if content_encoding not in {"", "identity"}:
            raise ValueError(f"Unsupported JD content encoding: {content_encoding}")
        body = response.read(MAX_JD_BYTES + 1)
        if len(body) > MAX_JD_BYTES:
            raise ValueError("JD response exceeds the 2 MiB limit")
        message = Message()
        message["content-type"] = headers.get("content-type", "")
        encoding = message.get_content_charset()
        return response.status, headers, body, encoding
    finally:
        connection.close()


def extract_html_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
        element.decompose()
    text = soup.get_text("\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


async def fetch_job_description(url: str) -> str:
    current_url = url.strip()
    for redirect_count in range(MAX_REDIRECTS + 1):
        hostname, port, addresses = _resolve_public_addresses(current_url)
        response = None
        last_connection_error: OSError | None = None
        for address in addresses:
            try:
                response = await asyncio.to_thread(
                    _request_pinned, current_url, hostname, address, port
                )
                break
            except OSError as error:
                last_connection_error = error
        if response is None:
            raise ValueError(f"Unable to connect to JD URL: {current_url}") from last_connection_error
        status, headers, body, encoding = response
        if status in {301, 302, 303, 307, 308}:
            if redirect_count == MAX_REDIRECTS:
                raise ValueError("JD URL exceeded the redirect limit")
            location = headers.get("location")
            if not location:
                raise ValueError("JD URL returned a redirect without a location")
            current_url = urljoin(current_url, location)
            continue
        content_type = headers.get("content-type", "").lower()
        if not any(allowed in content_type for allowed in ALLOWED_CONTENT_TYPES):
            raise ValueError(f"Unsupported JD content type: {content_type or 'unknown'}")
        raw_text = decode_html_bytes(body, encoding) if "html" in content_type else body.decode(
            encoding or "utf-8", errors="replace"
        )
        text = extract_html_text(raw_text) if "html" in content_type else raw_text.strip()
        if not text:
            raise ValueError("JD source did not contain readable text")
        return text
    raise ValueError("Unable to fetch JD URL")


def decode_html_bytes(body: bytes, header_encoding: str | None = None) -> str:
    """Decode HTML using HTTP metadata, document metadata, and common CJK fallbacks."""
    head = body[:4096].decode("ascii", errors="ignore")
    meta_match = re.search(
        r"<meta\b[^>]*(?:charset\s*=\s*[\"']?\s*|content\s*=\s*[\"'][^\"']*?charset\s*=\s*)"
        r"([\w.-]+)",
        head,
        re.IGNORECASE,
    )
    candidates = [header_encoding, meta_match.group(1) if meta_match else None, "utf-8", "gb18030", "big5"]
    tried: set[str] = set()
    for encoding in candidates:
        if not encoding:
            continue
        normalized = encoding.strip().casefold()
        if normalized in tried:
            continue
        tried.add(normalized)
        try:
            return body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


async def resolve_jd_source(source: str) -> tuple[str, dict[str, str]]:
    stripped = source.strip()
    if not stripped:
        raise ValueError("JD text or URL must not be empty")
    if is_url(stripped):
        return await fetch_job_description(stripped), {"kind": "url", "value": stripped}
    return stripped, {"kind": "text", "value": "inline"}
