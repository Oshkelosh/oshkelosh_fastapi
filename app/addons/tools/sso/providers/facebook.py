"""Facebook OAuth provider."""

from __future__ import annotations

from urllib.parse import urlencode

import httpx

from app.addons.tools.sso.config import FacebookProviderConfig
from app.addons.tools.sso.providers.base import OAuthProvider, ProviderDescriptor
from app.services.sso_accounts import SsoProfile

_GRAPH_VERSION = "v19.0"
_AUTH_URL = f"https://www.facebook.com/{_GRAPH_VERSION}/dialog/oauth"
_TOKEN_URL = f"https://graph.facebook.com/{_GRAPH_VERSION}/oauth/access_token"


class FacebookOAuthProvider(OAuthProvider):
    def __init__(self, config: FacebookProviderConfig) -> None:
        self._config = config
        self.descriptor = ProviderDescriptor(id="facebook", label="Facebook")

    def build_authorize_url(
        self,
        redirect_uri: str,
        state: str,
        code_challenge: str,
    ) -> str:
        params = {
            "client_id": self._config.app_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "email,public_profile",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> SsoProfile:
        async with httpx.AsyncClient(timeout=20.0) as client:
            token_resp = await client.get(
                _TOKEN_URL,
                params={
                    "client_id": self._config.app_id,
                    "client_secret": self._config.app_secret.get_secret_value(),
                    "redirect_uri": redirect_uri,
                    "code": code,
                    "code_verifier": code_verifier,
                },
            )
            token_resp.raise_for_status()
            access_token = token_resp.json()["access_token"]

            user_resp = await client.get(
                f"https://graph.facebook.com/{_GRAPH_VERSION}/me",
                params={"fields": "id,name,email", "access_token": access_token},
            )
            user_resp.raise_for_status()
            data = user_resp.json()

        email = data.get("email") or ""
        return SsoProfile(
            provider="facebook",
            subject=str(data.get("id", "")),
            email=email,
            email_verified=bool(email),
            full_name=data.get("name"),
        )
