import asyncio
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from career_resume_skill import ingestion
from career_resume_skill.ingestion import (
    decode_html_bytes,
    extract_html_text,
    fetch_job_description,
    resolve_jd_source,
    validate_public_url,
)


def test_decode_html_bytes_uses_meta_gb18030_when_header_is_missing() -> None:
    body = (
        '<meta charset="gb18030"><main>算法工程师：负责模型评估。</main>'
    ).encode("gb18030")

    assert "算法工程师" in decode_html_bytes(body)


def test_decode_html_bytes_prefers_explicit_header_encoding() -> None:
    body = b'<meta charset="gb18030"><main>PyTorch role</main>'

    assert "PyTorch role" in decode_html_bytes(body, "utf-8")


def test_html_extraction_removes_scripts_and_navigation() -> None:
    html = """
    <html><body><nav>Menu</nav><main><h1>Quant Developer</h1>
    <p>Build low latency C++ systems.</p></main><script>ignore()</script></body></html>
    """

    text = extract_html_text(html)

    assert text == "Quant Developer\nBuild low latency C++ systems."


def test_private_jd_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="public network"):
        validate_public_url("http://127.0.0.1/internal-job")


def test_dns_answer_with_any_private_address_is_rejected(monkeypatch) -> None:
    def resolve(*args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 80)),
        ]

    monkeypatch.setattr(ingestion.socket, "getaddrinfo", resolve)

    with pytest.raises(ValueError, match="public network"):
        ingestion._resolve_public_addresses("http://jobs.example/role")


def test_pinned_request_sends_http_and_reads_response() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", "7")
            self.end_headers()
            self.wfile.write(b"JD body")

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        port = server.server_address[1]
        result = ingestion._request_pinned(
            f"http://127.0.0.1:{port}/role", "127.0.0.1", "127.0.0.1", port
        )
    finally:
        server.shutdown()
        worker.join()
        server.server_close()

    status, headers, body, encoding = result
    assert status == 200
    assert headers["content-type"] == "text/plain; charset=utf-8"
    assert body == b"JD body"
    assert encoding == "utf-8"


def test_pinned_https_connection_uses_validated_ip_and_original_sni(monkeypatch) -> None:
    validated_ip = "93.184.216.34"
    calls = []

    class FakeSocket:
        def close(self) -> None:
            pass

    class FakeTLSContext:
        def wrap_socket(self, raw_socket, *, server_hostname):
            assert server_hostname == "jobs.example"
            return raw_socket

    monkeypatch.setattr(ingestion.socket, "create_connection", lambda target, timeout: calls.append(target) or FakeSocket())
    monkeypatch.setattr(ingestion.ssl, "create_default_context", FakeTLSContext)
    connection = ingestion._PinnedHTTPSConnection("jobs.example", validated_ip, 443)

    connection.connect()

    assert calls == [(validated_ip, 443)]
    connection.close()


def test_redirect_resolves_and_pins_each_host(monkeypatch) -> None:
    resolutions = []
    requests = []

    def resolve(url: str) -> tuple[str, int, list[str]]:
        hostname = ingestion.urlparse(url).hostname
        resolutions.append(hostname)
        address = "93.184.216.34" if hostname == "jobs.example" else "203.0.113.8"
        return hostname, 443, [address]

    def request(url: str, hostname: str, address: str, port: int):
        requests.append((hostname, address, port))
        if hostname == "jobs.example":
            return 302, {"location": "https://careers.example/final"}, b"", "utf-8"
        return 200, {"content-type": "text/plain; charset=utf-8"}, b"JD body", "utf-8"

    monkeypatch.setattr(ingestion, "_resolve_public_addresses", resolve)
    monkeypatch.setattr(ingestion, "_request_pinned", request)

    text = asyncio.run(fetch_job_description("https://jobs.example/start"))

    assert text == "JD body"
    assert resolutions == ["jobs.example", "careers.example"]
    assert requests == [
        ("jobs.example", "93.184.216.34", 443),
        ("careers.example", "203.0.113.8", 443),
    ]


def test_inline_jd_source_is_preserved() -> None:
    text, source = asyncio.run(resolve_jd_source("  AI Lab requires PyTorch.  "))

    assert text == "AI Lab requires PyTorch."
    assert source == {"kind": "text", "value": "inline"}
