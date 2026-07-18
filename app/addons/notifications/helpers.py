"""Shared transport helpers for notification addons."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any, Dict
from urllib.parse import urlparse


def _check_public_http_url(url: str) -> str | None:
    """Return a rejection reason unless ``url`` is http(s) to a public address.

    Webhook URLs are merchant-supplied; without this an admin-configured URL
    could probe internal services (SSRF). ponytail: resolve-then-connect still
    has a DNS-rebind race window; pin the resolved IP in the client to close it.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"scheme '{parsed.scheme}' not allowed"
    host = parsed.hostname
    if not host:
        return "missing host"
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        return f"cannot resolve host: {exc}"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            return f"host resolves to non-public address {ip}"
    return None


async def post_json_webhook(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    reason = await asyncio.to_thread(_check_public_http_url, url)
    if reason:
        return {"success": False, "error": f"Webhook URL rejected: {reason}"}
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            return {"success": True, "status_code": resp.status_code}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
