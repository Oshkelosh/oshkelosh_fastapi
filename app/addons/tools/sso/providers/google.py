"""Google OIDC provider."""

from __future__ import annotations

from urllib.parse import urlencode

import httpx

from app.addons.tools.sso.config import GoogleProviderConfig
from app.addons.tools.sso.providers.base import OAuthProvider, ProviderDescriptor
from app.services.sso_accounts import SsoProfile

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


class GoogleOAuthProvider(OAuthProvider):
    def __init__(self, config: GoogleProviderConfig) -> None:
        self._config = config
        self.descriptor = ProviderDescriptor(id="google", label="Google")

    def build_authorize_url(
        self,
        redirect_uri: str,
        state: str,
        code_challenge: str,
    ) -> str:
        params = {
            "client_id": self._config.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "online",
            "prompt": "select_account",
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> SsoProfile:
        async with httpx.AsyncClient(timeout=20.0) as client:
            token_resp = await client.post(
                _TOKEN_URL,
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
            access_token = token_resp.json()["access_token"]

            user_resp = await client.get(
                _USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            user_resp.raise_for_status()
            data = user_resp.json()

        email = data.get("email") or ""
        return SsoProfile(
            provider="google",
            subject=str(data.get("sub", "")),
            email=email,
            email_verified=bool(data.get("email_verified", False)),
            full_name=data.get("name"),
        )
