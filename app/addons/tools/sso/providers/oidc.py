"""Generic OIDC provider with discovery document support."""

from __future__ import annotations

from urllib.parse import urlencode

import httpx

from app.addons.tools.sso.config import OidcProviderConfig
from app.addons.tools.sso.providers.base import OAuthProvider, ProviderDescriptor
from app.services.sso_accounts import SsoProfile


class OidcOAuthProvider(OAuthProvider):
    def __init__(self, config: OidcProviderConfig) -> None:
        self._config = config
        provider_key = f"oidc_{config.provider_id}"
        self.descriptor = ProviderDescriptor(id=provider_key, label=config.display_name)
        self._discovery: dict | None = None

    async def _load_discovery(self) -> dict:
        if self._discovery is not None:
            return self._discovery
        issuer = self._config.issuer_url.rstrip("/")
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(f"{issuer}/.well-known/openid-configuration")
            resp.raise_for_status()
            self._discovery = resp.json()
        return self._discovery

    def build_authorize_url(
        self,
        redirect_uri: str,
        state: str,
        code_challenge: str,
    ) -> str:
        issuer = self._config.issuer_url.rstrip("/")
        auth_endpoint = f"{issuer}/authorize"
        if self._discovery:
            auth_endpoint = self._discovery.get("authorization_endpoint", auth_endpoint)
        params = {
            "client_id": self._config.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": self._config.scopes,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{auth_endpoint}?{urlencode(params)}"

    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> SsoProfile:
        discovery = await self._load_discovery()
        token_endpoint = discovery["token_endpoint"]
        userinfo_endpoint = discovery.get("userinfo_endpoint")

        async with httpx.AsyncClient(timeout=20.0) as client:
            token_resp = await client.post(
                token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": self._config.client_id,
                    "client_secret": self._config.client_secret.get_secret_value(),
                    "code_verifier": code_verifier,
                },
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()
            access_token = token_data["access_token"]

            if userinfo_endpoint:
                user_resp = await client.get(
                    userinfo_endpoint,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                user_resp.raise_for_status()
                data = user_resp.json()
            else:
                data = {}

        email = data.get("email") or ""
        email_verified = data.get("email_verified")
        if email_verified is None:
            email_verified = bool(email)
        return SsoProfile(
            provider=self.descriptor.id,
            subject=str(data.get("sub", "")),
            email=email,
            email_verified=bool(email_verified),
            full_name=data.get("name"),
        )

    async def prepare(self) -> None:
        """Preload discovery so authorize URL uses the correct endpoint."""
        await self._load_discovery()
