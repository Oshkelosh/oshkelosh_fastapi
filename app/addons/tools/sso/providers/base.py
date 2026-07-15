"""OAuth/OIDC provider abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.services.sso_accounts import SsoProfile


@dataclass
class ProviderDescriptor:
    """Public metadata for an enabled SSO provider."""

    id: str
    label: str


class OAuthProvider(ABC):
    """Provider-specific OAuth/OIDC implementation."""

    descriptor: ProviderDescriptor

    @abstractmethod
    def build_authorize_url(
        self,
        redirect_uri: str,
        state: str,
        code_challenge: str,
    ) -> str:
        """Return the IdP authorization URL."""

    @abstractmethod
    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> SsoProfile:
        """Exchange authorization code and return a normalized profile."""
