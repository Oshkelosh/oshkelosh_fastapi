from starlette.requests import Request

from app.core.rate_limit import _client_key


def _request_for(ip: str, headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers or [],
        "client": (ip, 12345),
    }
    return Request(scope)


def test_client_key_uses_remote_addr_without_trusted_proxy(monkeypatch):
    monkeypatch.setattr("app.core.rate_limit.settings.trusted_proxy_ips", [])
    request = _request_for(
        "10.0.0.1",
        headers=[(b"x-forwarded-for", b"203.0.113.10")],
    )
    assert _client_key(request) == "10.0.0.1"


def test_client_key_uses_forwarded_header_for_trusted_proxy(monkeypatch):
    monkeypatch.setattr("app.core.rate_limit.settings.trusted_proxy_ips", ["10.0.0.1"])
    monkeypatch.setattr(
        "app.core.rate_limit.settings.trusted_proxy_headers",
        ["x-forwarded-for", "x-real-ip"],
    )
    request = _request_for(
        "10.0.0.1",
        headers=[(b"x-forwarded-for", b"203.0.113.10, 10.0.0.1")],
    )
    assert _client_key(request) == "203.0.113.10"
