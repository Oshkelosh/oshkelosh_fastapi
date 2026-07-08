"""SSO flow orchestration: PKCE, state tokens, and provider registry."""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from jose import JWTError, jwt

from app.addons.tools.sso.config import SsoConfig
from app.addons.tools.sso.providers.base import OAuthProvider, ProviderDescriptor
from app.addons.tools.sso.providers.facebook import FacebookOAuthProvider
from app.addons.tools.sso.providers.google import GoogleOAuthProvider
from app.addons.tools.sso.providers.oidc import OidcOAuthProvider
from app.config import settings
from app.core.exceptions import AuthenticationError, ValidationError
from app.services.sso_accounts import find_or_create_sso_user


def public_app_url() -> str:
    if settings.public_app_url:
        return settings.public_app_url.rstrip("/")
    if settings.cors_origins:
        return settings.cors_origins[0].rstrip("/")
    return "http://localhost:8000"


def api_base_url() -> str:
    return f"{public_app_url()}{settings.api_v1_prefix}"


def callback_url(provider_id: str) -> str:
    return f"{api_base_url()}/tools/sso/{provider_id}/callback"


def generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def create_sso_state_token(
    provider: str,
    redirect_after: str,
    pkce_verifier: str,
) -> str:
    payload = {
        "type": "sso_state",
        "provider": provider,
        "redirect_after": redirect_after,
        "pkce_verifier": pkce_verifier,
        "exp": datetime.now(tz=timezone.utc) + timedelta(minutes=10),
        "iat": datetime.now(tz=timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_sso_state_token(token: str) -> dict[str, Any]:
    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    if payload.get("type") != "sso_state":
        raise JWTError("Invalid SSO state token")
    return payload


def create_sso_exchange_token(user_id: int) -> str:
    payload = {
        "type": "sso_exchange",
        "sub": str(user_id),
        "exp": datetime.now(tz=timezone.utc) + timedelta(seconds=60),
        "iat": datetime.now(tz=timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_sso_exchange_token(token: str) -> int:
    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    if payload.get("type") != "sso_exchange":
        raise JWTError("Invalid SSO exchange token")
    return int(payload["sub"])


def build_provider_registry(config: SsoConfig) -> dict[str, OAuthProvider]:
    providers: dict[str, OAuthProvider] = {}

    if config.google.enabled and config.google.client_id:
        secret = config.google.client_secret.get_secret_value()
        if secret:
            providers["google"] = GoogleOAuthProvider(config.google)

    if config.facebook.enabled and config.facebook.app_id:
        secret = config.facebook.app_secret.get_secret_value()
        if secret:
            providers["facebook"] = FacebookOAuthProvider(config.facebook)

    for oidc_cfg in config.oidc_providers:
        if not oidc_cfg.enabled or not oidc_cfg.client_id or not oidc_cfg.issuer_url:
            continue
        if not oidc_cfg.client_secret.get_secret_value():
            continue
        provider = OidcOAuthProvider(oidc_cfg)
        providers[provider.descriptor.id] = provider

    return providers


async def prepare_providers(providers: dict[str, OAuthProvider]) -> None:
    for provider in providers.values():
        prepare = getattr(provider, "prepare", None)
        if prepare is not None:
            await prepare()


def list_provider_descriptors(providers: dict[str, OAuthProvider]) -> List[ProviderDescriptor]:
    return [provider.descriptor for provider in providers.values()]


def build_authorize_url(
    providers: dict[str, OAuthProvider],
    provider_id: str,
    redirect_after: str = "/",
) -> str:
    provider = providers.get(provider_id)
    if provider is None:
        raise ValidationError(message=f"SSO provider '{provider_id}' is not enabled")

    verifier, challenge = generate_pkce_pair()
    state = create_sso_state_token(provider_id, redirect_after, verifier)
    redirect_uri = callback_url(provider_id)
    return provider.build_authorize_url(redirect_uri, state, challenge)


def build_public_providers(providers: dict[str, OAuthProvider]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for descriptor in list_provider_descriptors(providers):
        authorize = f"{api_base_url()}/tools/sso/{descriptor.id}/authorize"
        items.append(
            {
                "id": descriptor.id,
                "label": descriptor.label,
                "authorize_url": authorize,
            }
        )
    return items


async def handle_oauth_callback(
    session: Any,
    providers: dict[str, OAuthProvider],
    provider_id: str,
    code: str,
    state: str,
) -> tuple[int, str]:
    provider = providers.get(provider_id)
    if provider is None:
        raise ValidationError(message=f"SSO provider '{provider_id}' is not enabled")

    try:
        state_payload = decode_sso_state_token(state)
    except JWTError as exc:
        raise AuthenticationError(message="Invalid or expired SSO state") from exc

    if state_payload.get("provider") != provider_id:
        raise AuthenticationError(message="SSO state provider mismatch")

    redirect_after = state_payload.get("redirect_after") or "/"
    pkce_verifier = state_payload.get("pkce_verifier", "")
    redirect_uri = callback_url(provider_id)

    profile = await provider.exchange_code(code, redirect_uri, pkce_verifier)
    user = await find_or_create_sso_user(session, profile)
    exchange_token = create_sso_exchange_token(user.id)
    return user.id, redirect_after


def build_spa_callback_redirect(exchange_token: str, redirect_after: str = "/") -> str:
    params = {"exchange_token": exchange_token}
    if redirect_after and redirect_after != "/":
        params["redirect"] = redirect_after
    query = urlencode(params)
    return f"{public_app_url()}/auth/sso/callback?{query}"
