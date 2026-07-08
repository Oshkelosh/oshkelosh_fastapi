"""Shared transport helpers for notification addons."""

from __future__ import annotations

from typing import Any, Dict


async def post_json_webhook(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
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
