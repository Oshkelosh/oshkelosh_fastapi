"""Credential validation for SSO providers."""

from __future__ import annotations

import httpx

from app.addons.tools.sso.config import SsoConfig
from app.core.exceptions import ValidationError

_REQUIRED_OIDC_SCOPES = frozenset({"openid", "email"})


async def validate_sso_config(config: SsoConfig) -> None:
    """Verify enabled SSO providers are reachable and configured with required scopes."""
    if config.google.enabled:
        secret = config.google.client_secret.get_secret_value()
        if config.google.client_id and secret:
            if not secret.strip():
                raise ValidationError(message="Google client secret is required when Google SSO is enabled")

    if config.facebook.enabled:
        secret = config.facebook.app_secret.get_secret_value()
        if config.facebook.app_id and secret:
            if not secret.strip():
                raise ValidationError(message="Facebook app secret is required when Facebook SSO is enabled")

    for oidc_cfg in config.oidc_providers:
        if not oidc_cfg.enabled:
            continue
        if not oidc_cfg.issuer_url.strip():
            raise ValidationError(
                message=f"OIDC provider '{oidc_cfg.provider_id}' requires an issuer URL"
            )
        if not oidc_cfg.client_id.strip():
            raise ValidationError(
                message=f"OIDC provider '{oidc_cfg.provider_id}' requires a client ID"
            )
        secret = oidc_cfg.client_secret.get_secret_value()
        if not secret.strip():
            raise ValidationError(
                message=f"OIDC provider '{oidc_cfg.provider_id}' requires a client secret"
            )

        scopes = {part.strip() for part in oidc_cfg.scopes.split() if part.strip()}
        missing_scopes = _REQUIRED_OIDC_SCOPES - scopes
        if missing_scopes:
            raise ValidationError(
                message=(
                    f"OIDC provider '{oidc_cfg.provider_id}' is missing required scopes: "
                    f"{', '.join(sorted(missing_scopes))}"
                )
            )

        issuer = oidc_cfg.issuer_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{issuer}/.well-known/openid-configuration")
                resp.raise_for_status()
                discovery = resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise ValidationError(
                    message=(
                        f"OIDC provider '{oidc_cfg.provider_id}' issuer rejected the request "
                        "(check issuer URL and provider access)"
                    )
                ) from exc
            raise ValidationError(
                message=f"OIDC provider '{oidc_cfg.provider_id}' issuer is unreachable"
            ) from exc
        except Exception as exc:
            raise ValidationError(
                message=f"OIDC provider '{oidc_cfg.provider_id}' issuer is unreachable"
            ) from exc

        if not discovery.get("authorization_endpoint") or not discovery.get("token_endpoint"):
            raise ValidationError(
                message=(
                    f"OIDC provider '{oidc_cfg.provider_id}' discovery document is missing "
                    "required endpoints"
                )
            )
